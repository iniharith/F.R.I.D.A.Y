import asyncio
import ctypes
import datetime
import html
import inspect
import ipaddress
import math
import os
import re
import shutil
import subprocess
import time
import uuid
import webbrowser
from dataclasses import dataclass, field
from enum import Enum
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
import psutil
import socket

from core import config
from core.hands.reminders import ReminderScheduler
from core.vision.engine import VisionEngine
import ast


_LOCAL_VISION = VisionEngine()


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg", "head", "template"}:
            self._skip += 1
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "pre"}:
            self.parts.append("\n")
        if tag == "pre":
            self.parts.append("```\n")
        if tag in {"h1", "h2", "h3", "h4"}:
            self.parts.append("## ")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg", "head", "template"} and self._skip > 0:
            self._skip -= 1
        if tag == "pre":
            self.parts.append("\n```")

    def handle_data(self, data):
        if self._skip == 0 and data.strip():
            self.parts.append(data)


def _html_to_text(raw_html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(raw_html)
    except Exception:
        pass
    text = "".join(parser.parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_tags(raw: str) -> str:
    """Remove HTML tags and collapse whitespace for short search snippets."""
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()



class Risk(str, Enum):
    SAFE = "safe"
    CAREFUL = "careful"


@dataclass(frozen=True)
class ToolParameter:
    name: str
    description: str
    value_type: type = str
    required: bool = True

    @property
    def json_type(self) -> str:
        return {str: "string", int: "integer", float: "number", bool: "boolean"}.get(
            self.value_type, "string"
        )


@dataclass(frozen=True)
class ToolSpec:
    name: str
    risk: Risk
    description: str
    parameters: tuple[ToolParameter, ...] = ()

    def manifest_entry(self) -> dict:
        return {
            "name": self.name,
            "risk": self.risk.value,
            "description": self.description,
            "arguments": {parameter.name: parameter.description for parameter in self.parameters},
        }


# Populated from agent.MANIFEST once that compatibility manifest is defined.
TOOL_REGISTRY: dict[str, ToolSpec] = {}


def register_tool_manifest(manifest: list[dict]) -> dict[str, ToolSpec]:
    """Derive the canonical typed registry from the legacy public manifest."""
    registry: dict[str, ToolSpec] = {}
    schedule_types = {
        "timer": {"seconds": float, "label": str},
        "reminder": {"seconds": float, "message": str},
        "list_reminders": {},
        "cancel_reminders": {},
    }
    for item in manifest:
        name = str(item["name"])
        signature = None
        handler = getattr(TaskAgent, f"_{name}", None)
        if handler is not None:
            signature = inspect.signature(handler)
        parameters = []
        for argument, description in (item.get("arguments") or {}).items():
            parameter = signature.parameters.get(argument) if signature else None
            annotation = parameter.annotation if parameter else schedule_types.get(name, {}).get(argument, str)
            value_type = annotation if annotation in {str, int, float, bool} else str
            required = (
                parameter.default is inspect.Parameter.empty
                if parameter is not None
                else argument != "label"
            )
            parameters.append(ToolParameter(argument, str(description), value_type, required))
        registry[name] = ToolSpec(
            name=name,
            risk=Risk(item["risk"]),
            description=str(item["description"]),
            parameters=tuple(parameters),
        )
    TOOL_REGISTRY.clear()
    TOOL_REGISTRY.update(registry)
    return TOOL_REGISTRY


def get_tool_spec(name: str) -> ToolSpec | None:
    if not TOOL_REGISTRY:
        # Tool execution can be used without importing agent first. Importing it
        # initializes the registry from the legacy manifest without duplicating it.
        try:
            __import__("core.hands.agent")
        except ImportError:
            return None
    return TOOL_REGISTRY.get(name)


@dataclass
class ToolRequest:
    name: str
    args: dict
    risk: Risk
    title: str
    description: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)

    def public(self) -> dict:
        preview = {}
        for key, value in self.args.items():
            if key in {"content", "text"}:
                preview[key] = f"<{len(str(value))} characters>"
            elif key in {"old_string", "new_string"}:
                preview[key] = str(value)[:2000]
            else:
                preview[key] = str(value)[:4000]
        description = self.description
        if preview:
            details = "\n".join(f"{key}: {value}" for key, value in preview.items())
            description += "\n\nArguments:\n" + details
        return {
            "id": self.id,
            "name": self.name,
            "risk": self.risk.value,
            "title": self.title,
            "description": description,
            "arguments": preview,
        }


@dataclass
class ToolResult:
    ok: bool
    message: str
    speech: str | None = None
    data: dict = field(default_factory=dict)

    def public(self) -> dict:
        def bounded(value):
            if isinstance(value, str):
                return value[:6000]
            if isinstance(value, list):
                return [bounded(item) for item in value[:50]]
            if isinstance(value, dict):
                return {str(key)[:100]: bounded(item) for key, item in list(value.items())[:50]}
            return value

        return {
            "ok": self.ok,
            "message": self.message[:6000],
            "data": bounded(self.data),
        }


_APP_ALIASES = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "edge",
    "microsoft edge": "edge",
    "firefox": "firefox",
    "notepad": "notepad",
    "calculator": "calculator",
    "calc": "calculator",
    "file explorer": "explorer",
    "explorer": "explorer",
    "powershell": "powershell",
    "command prompt": "cmd",
    "cmd": "cmd",
    "terminal": "terminal",
    "windows terminal": "terminal",
    "task manager": "task_manager",
    "paint": "paint",
    "settings": "settings",
    "camera": "camera",
    "visual studio code": "vscode",
    "vs code": "vscode",
    "vscode": "vscode",
    "spotify": "spotify",
    "steam": "steam",
}

_APP_LABELS = {
    "chrome": "Chrome",
    "edge": "Microsoft Edge",
    "firefox": "Firefox",
    "notepad": "Notepad",
    "calculator": "Calculator",
    "explorer": "File Explorer",
    "powershell": "PowerShell",
    "cmd": "Command Prompt",
    "terminal": "Windows Terminal",
    "task_manager": "Task Manager",
    "paint": "Paint",
    "settings": "Windows Settings",
    "camera": "Camera",
    "vscode": "Visual Studio Code",
    "spotify": "Spotify",
    "steam": "Steam",
}

_APP_COMMANDS = {
    "chrome": [
        ["chrome.exe"],
        [r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"],
        [r"%LocalAppData%\Google\Chrome\Application\chrome.exe"],
    ],
    "edge": [
        ["msedge.exe"],
        [r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"],
    ],
    "firefox": [["firefox.exe"], [r"%ProgramFiles%\Mozilla Firefox\firefox.exe"]],
    "notepad": [["notepad.exe"]],
    "calculator": [["calc.exe"]],
    "explorer": [["explorer.exe"]],
    "powershell": [["powershell.exe"]],
    "cmd": [["cmd.exe"]],
    "terminal": [["wt.exe"], ["powershell.exe"]],
    "task_manager": [["taskmgr.exe"]],
    "paint": [["mspaint.exe"]],
    "settings": [["uri:ms-settings:"]],
    "camera": [["uri:microsoft.windows.camera:"]],
    "vscode": [
        ["code.exe"],
        [r"%LocalAppData%\Programs\Microsoft VS Code\Code.exe"],
    ],
    "spotify": [["spotify.exe"], [r"%AppData%\Spotify\Spotify.exe"]],
    "steam": [["steam.exe"], [r"%ProgramFiles(x86)%\Steam\steam.exe"]],
}

_PROCESS_NAMES = {
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
    "firefox": "firefox.exe",
    "notepad": "notepad.exe",
    "calculator": "CalculatorApp.exe",
    "powershell": "powershell.exe",
    "cmd": "cmd.exe",
    "terminal": "WindowsTerminal.exe",
    "paint": "mspaint.exe",
    "vscode": "Code.exe",
    "spotify": "Spotify.exe",
    "steam": "steam.exe",
}

_WEBSITES = {
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "reddit": "https://www.reddit.com",
    "wikipedia": "https://www.wikipedia.org",
}

_SENSITIVE_TEXT = re.compile(
    r"password|passcode|\bpin\b|api[ _-]?key|access[ _-]?token|secret|"
    r"private[ _-]?key|seed phrase|credit card|\bcvv\b|"
    r"\b(?:sk|hf)_[a-zA-Z0-9_-]{8,}",
    re.IGNORECASE,
)

# Hard defense-in-depth blocklist, shared by run_shell and background tasks,
# even past the confirmation gate. Word-boundary patterns so legitimate
# parameters (e.g. `Get-Date -Format o`) are never false-positived.
_BLOCKED_COMMAND_RE = re.compile(
    r"\bformat\s+[a-z]:"                       # format C:
    r"|\b(?:fdisk|diskpart|cleanmgr|defrag)\b"
    r"|\b(?:del|erase|rmdir|rd)\s+/s\b"
    r"|taskkill\b[^;\r\n]*\bexplorer\b"
    r"|\bnet\s+user\b"
    r"|\breg\s+delete\b"
    r"|remove-item\b[^;\r\n]*-recurse\b[^;\r\n]*[a-z]:\\",
    re.IGNORECASE,
)


def is_blocked_command(command: str) -> bool:
    """True when a shell command matches the destructive blocklist."""
    return bool(_BLOCKED_COMMAND_RE.search(command or ""))


class TaskAgent:
    def __init__(self, vision_analyzer=None) -> None:
        self.pending: dict[str, ToolRequest] = {}
        self._authorizations: dict[str, tuple[ToolRequest, str]] = {}
        self.scheduler: ReminderScheduler | None = None
        self.background: "BackgroundManager | None" = None
        self.vision_analyzer = vision_analyzer
        self.subagent_runner = None

    def _request(
        self,
        name: str,
        args: dict,
        risk: Risk,
        title: str,
        description: str,
    ) -> ToolRequest:
        return ToolRequest(name, args, risk, title, description)

    @staticmethod
    def _clean_input(text: str) -> str:
        text = text.strip()
        text = re.sub(r"^(?:hey\s+)?friday[,\s]+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^please\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+please[.!?]*$", "", text, flags=re.IGNORECASE)
        return text.strip()

    @staticmethod
    def _duration(value: str, unit: str) -> float:
        amount = float(value)
        if unit.startswith("minute"):
            amount *= 60
        elif unit.startswith("hour"):
            amount *= 3600
        return amount

    @staticmethod
    def _duration_label(seconds: float) -> str:
        if seconds >= 3600 and seconds % 3600 == 0:
            return f"{seconds / 3600:g} hour(s)"
        if seconds >= 60 and seconds % 60 == 0:
            return f"{seconds / 60:g} minute(s)"
        return f"{seconds:g} second(s)"

    def parse(self, raw_text: str) -> ToolRequest | None:
        text = self._clean_input(raw_text)
        lower = text.lower().strip(" .!?")

        if re.fullmatch(r"fix (?:my |the )?code(?: in (.+))?", lower, re.IGNORECASE):
            file_path = ""
            match = re.search(r"in (.+)", lower)
            if match:
                file_path = match.group(1).strip()
            return self._request(
                "self_edit",
                {"file_path": file_path},
                Risk.CAREFUL,
                "Self-Correction",
                "Analyze and fix a bug in the internal source code",
            )

        if re.fullmatch(
            r"(?:list|show)(?: my)? (?:timers|reminders)|"
            r"what (?:timers|reminders) do i have",
            lower,
        ):
            return self._request(
                "list_reminders",
                {},
                Risk.SAFE,
                "List reminders",
                "List pending timers and reminders",
            )

        if re.fullmatch(r"cancel all (?:timers|reminders)", lower):
            return self._request(
                "cancel_reminders",
                {},
                Risk.CAREFUL,
                "Cancel all reminders",
                "Cancel every pending timer and reminder",
            )

        timer = re.fullmatch(
            r"(?:set|start) (?:a )?timer(?: for)? (\d+(?:\.\d+)?) "
            r"(seconds?|minutes?|hours?)(?: (?:called|for) (.+))?",
            lower,
        )
        if timer:
            seconds = self._duration(timer.group(1), timer.group(2))
            label = timer.group(3) or ""
            return self._request(
                "timer",
                {"seconds": seconds, "label": label},
                Risk.SAFE,
                "Set timer",
                f"Set a {self._duration_label(seconds)} timer",
            )

        reminder = re.fullmatch(
            r"remind me in (\d+(?:\.\d+)?) (seconds?|minutes?|hours?) "
            r"(?:to|that) (.+)",
            text,
            re.IGNORECASE,
        )
        if reminder:
            seconds = self._duration(reminder.group(1), reminder.group(2).lower())
            message = reminder.group(3).strip()
            return self._request(
                "reminder",
                {"seconds": seconds, "message": message},
                Risk.SAFE,
                "Set reminder",
                f"Remind you in {self._duration_label(seconds)} to {message}",
            )

        search = re.fullmatch(
            r"(?:search(?: the web| google)? for|google|look up)\s+(.+)",
            text,
            re.IGNORECASE,
        )
        if search and not re.match(
            r"(?:a |the )?(?:file|document)\b", search.group(1), re.IGNORECASE
        ):
            query = search.group(1).strip()
            return self._request(
                "web_search",
                {"query": query},
                Risk.SAFE,
                "Web search",
                f"Search the web for {query}",
            )

        weather = re.fullmatch(
            r"(?:what(?:'s| is) the )?weather(?: like)?(?: in| for)?\s*(.*)",
            text,
            re.IGNORECASE,
        )
        if weather:
            location = weather.group(1).strip()
            return self._request(
                "weather",
                {"location": location},
                Risk.SAFE,
                "Weather",
                f"Check the weather{f' in {location}' if location else ''}",
            )

        file_search = re.fullmatch(
            r"(?:find|search for|locate) (?:a |the )?(?:file|document)"
            r"(?: named| called)?\s+(.+)",
            text,
            re.IGNORECASE,
        )
        if file_search:
            query = file_search.group(1).strip(" \"'")
            return self._request(
                "find_files",
                {"query": query},
                Risk.SAFE,
                "Find files",
                f"Search your common folders for {query}",
            )

        directory_query = re.fullmatch(
            r"(?:what(?:'s|s)?(?:\s+(?:is|are|about))?(?:\s+(?:in|inside|under|on))?\s+|"
            r"(?:list|show|check)(?: me)?(?:\s+(?:what(?:'s|s)?(?:\s+(?:is|are)))?)?"
            r"(?:\s+(?:in|inside|under|on))?\s+)"
            r"(?:my |the )?(downloads?|documents?|desktop)(?:\s+(?:folder|directory))?",
            lower,
        )
        if directory_query:
            folder = directory_query.group(1).lower()
            folder = "Downloads" if folder.startswith("download") else (
                "Documents" if folder.startswith("document") else "Desktop"
            )
            path = Path.home() / folder
            return self._request(
                "list_directory",
                {"path": str(path)},
                Risk.SAFE,
                f"List {folder}",
                f"List the real contents of {path}",
            )

        if re.fullmatch(r"(?:tile|organize|arrange) (?:my )?(?:windows|apps)", lower):
            return self._request(
                "tile_windows",
                {},
                Risk.CAREFUL,
                "Tile windows",
                "Arrange open windows in a grid layout",
            )

        if re.fullmatch(r"(?:maximize|fullscreen) (?:the )?(?:current|active) (?:window|app)", lower):
            return self._request(
                "maximize_window",
                {},
                Risk.CAREFUL,
                "Maximize window",
                "Maximize the currently active window",
            )

        if re.fullmatch(r"(?:minimize) (?:the )?(?:current|active) (?:window|app)", lower):
            return self._request(
                "minimize_window",
                {},
                Risk.CAREFUL,
                "Minimize window",
                "Minimize the currently active window",
            )

        if re.fullmatch(r"(?:system (?:status|health))|(?:what(?:'s| is) (?:my |the )?system (?:status|health))|(?:how(?:'s| is) (?:my )?(?:computer|pc|system) (?:doing)?)", lower):
            return self._request(
                "system_health",
                {},
                Risk.SAFE,
                "System health check",
                "Check CPU, RAM, disk, and GPU status",
            )

        if re.fullmatch(r"(?:list|show) (?:running )?(?:apps|applications|processes)", lower):
            return self._request(
                "list_processes",
                {},
                Risk.SAFE,
                "List processes",
                "List currently running applications",
            )

        if re.fullmatch(r"(?:what(?:'s| is) (?:the )?weather(?: like)?(?: in| for)?\s*(.*))", text, re.IGNORECASE):
            pass  # let it fall through to existing weather handler

        if re.fullmatch(r"(?:take (?:a )?screenshot|screenshot|capture (?:the )?screen)", lower):
            return self._request(
                "screenshot",
                {},
                Risk.CAREFUL,
                "Take screenshot",
                "Capture the primary screen",
            )
        if re.fullmatch(r"(?:what(?:'s| is) on (?:my |the )?screen)|(?:look at (?:my |the )?screen)", lower, re.IGNORECASE):
            return self._request(
                "vision_screen",
                {},
                Risk.CAREFUL,
                "Analyze screen",
                "Read and describe the current screen content",
            )
        if re.fullmatch(r"(?:what(?:'s| is) in (?:front of you|the camera))|(?:look at the camera)", lower, re.IGNORECASE):
            return self._request(
                "vision_camera",
                {},
                Risk.CAREFUL,
                "Analyze camera",
                "Capture and describe the current camera view",
            )
        inspect = re.fullmatch(
            r"(?:see|l[o0]ok at|what(?:'s| is) (?:in|inside|on)) "
            r"(?:(?:the|that|my)?\s*(?:image|picture|photo|file)\s+)?(.+)",
            lower,
            re.IGNORECASE,
        )
        if inspect and self._looks_like_image_path(inspect.group(1)):
            return self._request(
                "inspect_image",
                {"path": inspect.group(1).strip(" \"'.!?"), "prompt": "Describe what is inside this image accurately."},
                Risk.CAREFUL,
                "Inspect image",
                f"Read and describe the image at {inspect.group(1).strip()}",
            )
        volume = re.fullmatch(

            r"(?:turn )?(?:the )?volume (up|down)|"
            r"turn (up|down) (?:the )?volume|"
            r"(?:mute|unmute)(?: the)?(?: volume)?",
            lower,
        )
        if volume:
            action = volume.group(1) or volume.group(2) or "mute"
            return self._request(
                "volume",
                {"action": action},
                Risk.SAFE,
                "Volume control",
                f"Turn volume {action}",
            )

        open_match = re.fullmatch(r"(?:open|launch|start)\s+(.+)", text, re.IGNORECASE)
        if open_match:
            target = open_match.group(1).strip(" \"'.!?")
            lookup_target = target.lower()
            if lookup_target in _APP_ALIASES:
                app_id = _APP_ALIASES[lookup_target]
                label = _APP_LABELS[app_id]
                return self._request(
                    "open_app",
                    {"app_id": app_id},
                    Risk.SAFE,
                    "Open application",
                    f"Open {label}",
                )
            if lookup_target in _WEBSITES:
                return self._request(
                    "open_url",
                    {"url": _WEBSITES[lookup_target], "label": lookup_target.title()},
                    Risk.SAFE,
                    "Open website",
                    f"Open {lookup_target.title()}",
                )
            if re.fullmatch(r"(?:https?://|www\.)[^\s]+", target, re.IGNORECASE):
                url = target if target.lower().startswith("http") else f"https://{target}"
                return self._request(
                    "open_url",
                    {"url": url, "label": url},
                    Risk.SAFE,
                    "Open website",
                    f"Open {url}",
                )

        if re.fullmatch(r"(?:read|show) (?:my |the )?clipboard", lower) or re.fullmatch(
            r"what(?:'s| is) on (?:my |the )?clipboard", lower
        ):
            return self._request(
                "read_clipboard",
                {},
                Risk.CAREFUL,
                "Read clipboard",
                "Display the current clipboard text in FRIDAY's HUD",
            )

        type_match = re.fullmatch(r"type\s+[\"']?(.+?)[\"']?", text, re.IGNORECASE)
        if type_match:
            typed = type_match.group(1).strip()
            return self._request(
                "type_text",
                {"text": typed},
                Risk.CAREFUL,
                "Type into active window",
                f"Type {typed[:120]} after a 3-second window-focus delay",
            )

        close_match = re.fullmatch(r"(?:close|quit|exit)\s+(.+)", text, re.IGNORECASE)
        if close_match:
            target = close_match.group(1).strip(" \"'.!?").lower()
            if target in _APP_ALIASES and _APP_ALIASES[target] in _PROCESS_NAMES:
                app_id = _APP_ALIASES[target]
                return self._request(
                    "close_app",
                    {"app_id": app_id},
                    Risk.CAREFUL,
                    "Close application",
                    f"Close {_APP_LABELS[app_id]}; unsaved work may be lost",
                )

        if re.fullmatch(r"(?:shut down|shutdown)(?: the)? (?:computer|pc)", lower):
            return self._request(
                "power",
                {"action": "shutdown"},
                Risk.CAREFUL,
                "Shut down computer",
                "Shut down Windows after a 10-second safety delay",
            )
        if re.fullmatch(r"restart(?: the)? (?:computer|pc)", lower):
            return self._request(
                "power",
                {"action": "restart"},
                Risk.CAREFUL,
                "Restart computer",
                "Restart Windows after a 10-second safety delay",
            )
        if re.fullmatch(r"(?:put (?:the )?(?:computer|pc) to sleep|sleep (?:the )?(?:computer|pc))", lower):
            return self._request(
                "power",
                {"action": "sleep"},
                Risk.CAREFUL,
                "Sleep computer",
                "Put the computer to sleep immediately",
            )
        if re.fullmatch(
            r"(?:sign ?(?:me )?out|signout|log ?(?:me )?off|logoff|logout)"
            r"(?: of (?:the )?(?:computer|pc|windows))?",
            lower,
        ):
            return self._request(
                "power",
                {"action": "signout"},
                Risk.CAREFUL,
                "Sign out of Windows",
                "Sign out of Windows after a 10-second safety delay",
            )

        recycle = re.fullmatch(
            r"(?:delete|remove|recycle) (?:the )?(?:file )?(.+)",
            text,
            re.IGNORECASE,
        )
        if recycle:
            path = recycle.group(1).strip(" \"'")
            return self._request(
                "recycle_file",
                {"path": path},
                Risk.CAREFUL,
                "Move file to Recycle Bin",
                f"Move {path} to the Recycle Bin",
            )

        # ============ GENERAL-PURPOSE TOOLS (fallback) ============
        # Unlock real, multi-purpose capability. Anything risky is CAREFUL
        # (confirm-gated in the HUD). Falls through to a normal reply if none match.

        # start a detached background task (subagent)
        background_status = re.fullmatch(
            r"(?:(?:list|show|check)\s+)?(?:what\s+are\s+|what(?:'s| is)\s+)?"
            r"(?:my\s+|the\s+)?(?:running\s+)?background\s+(?:tasks?|jobs?)",
            lower,
        )
        if background_status:
            return self._request(
                "background_status",
                {},
                Risk.SAFE,
                "Background task status",
                "Check the status and recent output of background tasks",
            )

        background_run = re.fullmatch(
            r"(?:run|start|execute)\s+(.+?)\s+in\s+(?:the\s+)?background",
            text,
            re.IGNORECASE,
        )
        if background_run:
            command = background_run.group(1).strip(' "`')
            if command:
                return self._request(
                    "run_background",
                    {"command": command},
                    Risk.CAREFUL,
                    "Run in background",
                    f"Start a detached background task: {command[:160]}",
                )

        # run / execute a shell command or code
        run_match = re.fullmatch(
            r"(?:run|execute|do|type)(?:\s+this)?\s+(?:command\s*[:\-]\s*|the command\s*[:\-]\s*)?(.+)",
            text,
            re.IGNORECASE,
        )
        if run_match:
            command = run_match.group(1).strip(' "\'`')
            if command and not self._looks_like_plain_chat(command, text):
                return self._request(
                    "run_shell",
                    {"command": command},
                    Risk.CAREFUL,
                    "Run command",
                    f"Execute: {command[:160]}",
                )

        # read the contents of a file
        read_match = re.fullmatch(
            r"(?:read|show|print|display|open|cat|get)\s+(?:me\s+)?(?:the\s+(?:contents?|text|content)\s+of\s+)?[:\-]?\s?(.+)",
            text,
            re.IGNORECASE,
        )
        if read_match:
            path = read_match.group(1).strip(" \"'")
            if self._is_probable_file_path(path):
                return self._request(
                    "read_file",
                    {"path": path},
                    Risk.SAFE,
                    "Read file",
                    f"Read the file {path}",
                )

        # write / create a file
        write_match = re.fullmatch(
            r"(?:write|save|create|overwrite)\s+(.+?)\s+(?:with|to|as|containing|that says)\s+(.+)",
            text,
            re.IGNORECASE,
        )
        if write_match:
            path = write_match.group(1).strip(" \"'")
            content = write_match.group(2).strip(" \"'")
            if self._is_probable_file_path(path):
                return self._request(
                    "write_file",
                    {"path": path, "content": content},
                    Risk.CAREFUL,
                    "Write file",
                    f"Write content to {path}",
                )

        # calculate arithmetic / math
        calc_match = re.fullmatch(
            r"(?:calculate|compute|what is|what's|evaluate|solve)\s+(.+)",
            text,
            re.IGNORECASE,
        )
        if calc_match:
            expr = calc_match.group(1).strip(" ?")
            if self._is_math_expr(expr):
                return self._request(
                    "math",
                    {"expression": expr},
                    Risk.SAFE,
                    "Calculate",
                    f"Calculate {expr[:120]}",
                )

        # fetch / summarize a web page
        fetch_match = re.fullmatch(
            r"(?:fetch|open|load|summarize|what's on|what is on|get|scrape)\s+(?:the page\s+)?(https?://[^\s]+|www\.[^\s]+)",
            text,
            re.IGNORECASE,
        )
        if fetch_match:
            raw = fetch_match.group(1).strip()
            url = raw if raw.lower().startswith("http") else f"https://{raw}"
            return self._request(
                "fetch_url",
                {"url": url},
                Risk.SAFE,
                "Fetch web page",
                f"Fetch and summarize {url[:120]}",
            )

        return None

    @staticmethod
    def _is_probable_file_path(candidate: str) -> bool:
        if not candidate:
            return False
        if re.match(r"^[A-Za-z]:[\\/]", candidate) or candidate.startswith(("/", "~", ".", "\\")):
            return True
        if candidate.lower().endswith(
            (".py", ".txt", ".md", ".json", ".csv", ".log", ".js", ".html",
             ".css", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml", ".sh",
             ".bat", ".ps1", ".ini", ".env", ".ts", ".tsx", ".java", ".c",
             ".cpp", ".h", ".go", ".rs", ".sql")
        ):
            return True
        return "/" in candidate or "\\" in candidate

    @staticmethod
    def _is_math_expr(expr: str) -> bool:
        if not expr or len(expr) > 120:
            return False
        if re.search(r"[A-Za-z]{2,}", expr):  # allow single-char math constants only
            words = re.findall(r"[A-Za-z]{2,}", expr)
            allowed = {
                "pi", "e", "sin", "cos", "tan", "sqrt", "log", "abs",
                "floor", "ceil", "round", "exp", "factorial",
            }
            for w in words:
                if w not in allowed:
                    return False
        try:
            ast.parse(expr.replace("^", "**"), mode="eval")
        except SyntaxError:
            return False
        return True

    @staticmethod
    def _looks_like_plain_chat(command: str, full_text: str) -> bool:
        # Avoid swallowing normal sentences as commands.
        if len(command.split()) > 12:
            return True
        if re.match(r"^(?:the|a|an|my|me|it|i|you|we)\b", command, re.IGNORECASE):
            return True
        return False

    def queue_confirmation(self, request: ToolRequest) -> None:
        spec = get_tool_spec(request.name)
        if spec is None or spec.risk is not Risk.CAREFUL:
            return
        request.risk = spec.risk
        self._cleanup_pending()
        self.pending.clear()
        self.pending[request.id] = request

    def _cleanup_pending(self) -> None:
        now = time.time()
        expired = [
            request_id
            for request_id, request in self.pending.items()
            if now - request.created_at > config.TASK_CONFIRM_SECONDS
        ]
        for request_id in expired:
            self.pending.pop(request_id, None)

    def latest_pending(self) -> ToolRequest | None:
        self._cleanup_pending()
        if not self.pending:
            return None
        return max(self.pending.values(), key=lambda request: request.created_at)

    def resolve(self, request_id: str, approved: bool) -> ToolRequest | None:
        self._cleanup_pending()
        request = self.pending.pop(request_id, None)
        if request is not None and approved:
            self.authorize(request)
            return request
        return None

    def authorize(self, request: ToolRequest) -> bool:
        """Issue a one-use in-process capability after trusted user approval."""
        spec = get_tool_spec(request.name)
        if spec is None or spec.risk is not Risk.CAREFUL:
            return False
        request.risk = spec.risk
        self._authorizations[request.id] = (request, self._request_fingerprint(request))
        return True

    @staticmethod
    def _request_fingerprint(request: ToolRequest) -> str:
        try:
            arguments = repr(sorted(request.args.items()))
        except Exception:
            arguments = repr(request.args)
        return f"{request.name}\0{arguments}"

    @staticmethod
    def confirmation_decision(text: str) -> bool | None:
        cleaned = text.lower().strip(" .!?")
        if cleaned in {"confirm", "confirmed", "yes", "yes please", "do it", "proceed", "approve"}:
            return True
        if cleaned in {"no", "cancel", "deny", "stop", "never mind", "do not"}:
            return False
        return None

    async def execute(self, request: ToolRequest) -> ToolResult:
        spec = get_tool_spec(request.name)
        if spec is None:
            return ToolResult(
                False,
                "That tool is not available, Boss.",
                data={"error": "unknown_tool", "tool": request.name},
            )
        request.risk = spec.risk
        if spec.risk is Risk.CAREFUL:
            authorized = self._authorizations.pop(request.id, None)
            if (
                authorized is None
                or authorized[0] is not request
                or authorized[1] != self._request_fingerprint(request)
            ):
                return ToolResult(
                    False,
                    "This action requires fresh user confirmation, Boss.",
                    data={"error": "authorization_required", "tool": request.name},
                )
        if request.name in {
            "timer",
            "reminder",
            "list_reminders",
            "cancel_reminders",
        }:
            return await self._schedule(request)
        if request.name == "subagent":
            task = str(request.args.get("task") or "").strip()
            if not task:
                return ToolResult(False, "A sub-agent needs a task to work on, Boss.")
            if self.subagent_runner is None:
                return ToolResult(
                    False,
                    "The sub-agent runner isn't active right now, Boss.",
                )
            return await self.subagent_runner(task)
        handlers = {
            "open_app": self._open_app,
            "open_url": self._open_url,
            "web_search": self._web_search,
            "weather": self._weather,
            "find_files": self._find_files,
            "list_directory": self._list_directory,
            "file_info": self._file_info,
            "search_text": self._search_text,
            "replace_in_file": self._replace_in_file,
            "create_directory": self._create_directory,
            "copy_path": self._copy_path,
            "move_path": self._move_path,
            "edit_own_file": self._edit_own_file,
            "current_time": self._current_time,
            "screenshot": self._screenshot,
            "vision_screen": self._vision_screen,
            "vision_camera": self._vision_camera,
            "inspect_image": self._inspect_image,
            "self_edit": self._self_edit,
            "apply_fix": self._apply_fix,
            "tile_windows": self._tile_windows,
            "maximize_window": self._maximize_window,
            "minimize_window": self._minimize_window,
            "system_health": self._system_health,
            "list_processes": self._list_processes,
            "volume": self._volume,
            "read_clipboard": self._read_clipboard,
            "type_text": self._type_text,
            "close_app": self._close_app,
            "power": self._power,
            "recycle_file": self._recycle_file,
            "run_shell": self._run_shell,
            "run_background": self._run_background,
            "background_status": self._background_status,
            "read_file": self._read_file,
            "write_file": self._write_file,
            "math": self._math,
            "fetch_url": self._fetch_url,
            "git_status": self._git_status,
            "git_mutate": self._git_mutate,
        }
        handler = handlers.get(request.name)
        if handler is None:
            return ToolResult(False, "That tool is not available, Boss.")
        try:
            args = dict(request.args)
            if request.name == "open_app":
                requested = str(args.get("app_id", "")).strip().lower()
                args["app_id"] = _APP_ALIASES.get(requested, requested)
                if args["app_id"] not in _APP_COMMANDS:
                    return ToolResult(False, f"Unknown application: {requested or 'empty value'}.")
            if request.name == "close_app":
                requested = str(args.get("app_id", "")).strip().lower()
                args["app_id"] = _APP_ALIASES.get(requested, requested)
                if args["app_id"] not in _PROCESS_NAMES:
                    return ToolResult(False, f"Unknown application: {requested or 'empty value'}.")
            if request.name == "volume" and args.get("action") not in {"up", "down", "mute"}:
                return ToolResult(False, "Volume action must be up, down, or mute.")
            if request.name == "power" and args.get("action") not in {"shutdown", "restart", "sleep", "signout"}:
                return ToolResult(False, "Power action must be shutdown, restart, sleep, or signout.")
            signature = inspect.signature(handler)
            signature.bind(**args)
            return await asyncio.to_thread(handler, **args)
        except TypeError as exc:
            return ToolResult(False, f"Invalid arguments for {request.name}: {exc}")
        except Exception as exc:
            return ToolResult(False, f"Task failed: {exc}")

    async def _schedule(self, request: ToolRequest) -> ToolResult:
        if self.scheduler is None:
            return ToolResult(False, "The reminder system is unavailable, Boss.")
        if request.name == "list_reminders":
            pending = self.scheduler.list_pending()
            if not pending:
                return ToolResult(True, "You have no pending timers or reminders, Boss.")
            lines = []
            for item in pending:
                remaining = max(0.0, item["due_at"] - time.time())
                lines.append(
                    f"- {item['message']} (in {self._duration_label(round(remaining))})"
                )
            message = f"You have {len(lines)} pending item(s):\n" + "\n".join(lines)
            return ToolResult(
                True,
                message,
                speech=f"You have {len(lines)} pending timer or reminder item(s), Boss.",
            )
        if request.name == "cancel_reminders":
            count = await self.scheduler.cancel_all()
            return ToolResult(True, f"Cancelled {count} pending timer or reminder item(s), Boss.")
        seconds = float(request.args["seconds"])
        if not math.isfinite(seconds) or not 0 < seconds <= 365 * 24 * 3600:
            return ToolResult(False, "Timer duration must be between 1 second and 365 days.")
        persistent_text = str(request.args.get("message") or request.args.get("label") or "")
        if _SENSITIVE_TEXT.search(persistent_text):
            return ToolResult(
                False,
                "I won't store passwords, tokens, or other credentials in reminders, Boss.",
            )
        if request.name == "timer":
            label = request.args.get("label") or ""
            notification = f"{label.title() + ' t' if label else 'T'}imer complete, Boss."
            message = f"Timer set for {self._duration_label(seconds)}, Boss."
        else:
            reminder = request.args["message"]
            notification = f"Reminder, Boss: {reminder}"
            message = f"I'll remind you in {self._duration_label(seconds)}, Boss."
        reminder_id = await self.scheduler.add(seconds, notification)
        return ToolResult(True, message, data={"reminder_id": reminder_id})

    @staticmethod
    def _resolve_executable(candidate: str) -> str | None:
        expanded = os.path.expandvars(candidate)
        if Path(expanded).exists():
            return expanded
        return shutil.which(candidate)

    def _open_app(self, app_id: str) -> ToolResult:
        for command in _APP_COMMANDS[app_id]:
            if command[0].startswith("uri:"):
                os.startfile(command[0][4:])
                return ToolResult(True, f"Opening {_APP_LABELS[app_id]}, Boss.")
            executable = self._resolve_executable(command[0])
            if executable:
                subprocess.Popen(
                    [executable, *command[1:]],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return ToolResult(True, f"Opening {_APP_LABELS[app_id]}, Boss.")
        return ToolResult(False, f"I couldn't find {_APP_LABELS[app_id]} on this computer, Boss.")

    @staticmethod
    def _open_url(url: str, label: str = "") -> ToolResult:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return ToolResult(False, "I blocked an invalid website address, Boss.")
        opened = webbrowser.open(url)
        label = label or url
        return ToolResult(
            bool(opened),
            f"Opening {label}, Boss."
            if opened
            else f"I couldn't open {label}, Boss.",
        )

    @staticmethod
    def _web_search(query: str) -> ToolResult:
        """Return real web search results (title/url/snippet) into context.

        Google is the default engine: the browser opens Google, and we try to
        parse Google's HTML results first. Because Google blocks automated HTML
        scraping (it returns an empty/JS-only page to bots), we fall back to
        Bing's HTML results, which parse reliably, so FRIDAY always has real,
        actionable results in context. The browser link always points at Google.
        """
        BROWSER_UA = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        try:
            webbrowser.open(f"https://www.google.com/search?q={quote(query)}")
        except Exception:
            pass

        def parse_bing(html_text: str) -> list[tuple[str, str, str]]:
            results: list[tuple[str, str, str]] = []
            for block in re.split(r'<li class="b_algo"', html_text)[1:]:
                title_m = re.search(r'<h2[^>]*><a[^>]*>(.*?)</a>', block, re.DOTALL)
                cite_m = re.search(r'<cite[^>]*>(.*?)</cite>', block, re.DOTALL)
                snip_m = re.search(
                    r'class="b_caption"[^>]*>(.*?)(?:</p>|<div)', block, re.DOTALL
                )
                title = _strip_tags(title_m.group(1)) if title_m else ""
                url = _strip_tags(cite_m.group(1)) if cite_m else ""
                snippet = _strip_tags(snip_m.group(1)) if snip_m else ""
                if title and url:
                    results.append((title, url, snippet))
                if len(results) >= 8:
                    break
            return results

        def parse_google(html_text: str) -> list[tuple[str, str, str]]:
            results: list[tuple[str, str, str]] = []
            blocks = re.split(r'class="g"[^>]*>|<div class="g "', html_text)
            for block in blocks[1:]:
                title_m = re.search(r'<h3[^>]*>(.*?)</h3>', block, re.DOTALL)
                url_m = re.search(r'<a[^>]*href="(https?://[^"]+)"', block)
                snip_m = re.search(
                    r'(?:VwiC3b|IsZvec)[^>]*>(.*?)</div>', block, re.DOTALL
                )
                title = _strip_tags(title_m.group(1)) if title_m else ""
                url = url_m.group(1) if url_m else ""
                snippet = _strip_tags(snip_m.group(1)) if snip_m else ""
                if title and url:
                    results.append((title, url, snippet))
                if len(results) >= 8:
                    break
            return results

        def fetch(engine_url: str, params: dict) -> str:
            resp = requests.get(
                engine_url,
                params=params,
                timeout=15,
                headers={
                    "User-Agent": BROWSER_UA,
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            resp.raise_for_status()
            return resp.text

        results: list[tuple[str, str, str]] = []

        # 1) Google first (default engine).
        try:
            html_text = fetch(
                "https://www.google.com/search",
                {"q": query, "num": "10", "hl": "en"},
            )
            results = parse_google(html_text)
            engine = "Google"
        except Exception:
            results = []
            engine = "Google"

        # 2) Fall back to Bing if Google returned nothing usable.
        if not results:
            try:
                html_text = fetch(
                    "https://www.bing.com/search",
                    {"q": query, "count": "10", "setlang": "en"},
                )
                results = parse_bing(html_text)
                engine = "Bing fallback (Google blocked automated access)"
            except Exception:
                results = []
                engine = "Google"

        if not results:
            return ToolResult(
                True, f"No web results found for \"{query}\" (via {engine}), Boss."
            )

        lines = [f"Web search results for \"{query}\" (via {engine}):"]
        for index, (title, url, snippet) in enumerate(results, 1):
            lines.append(f"{index}. {title} — {url}")
            if snippet:
                lines.append(f"   {snippet}")
        text = "\n".join(lines)
        return ToolResult(
            True,
            text,
            data={"engine": engine, "query": query, "results": [
                {"title": t, "url": u, "snippet": s} for t, u, s in results
            ]},
        )

    @staticmethod
    def _git_status(action: str = "status", path: str = "") -> ToolResult:
        return TaskAgent._git_run(action, path, message="", mutate=False)

    @staticmethod
    def _git_mutate(action: str = "commit", path: str = "", message: str = "") -> ToolResult:
        return TaskAgent._git_run(action, path, message=message, mutate=True)

    def _subagent(self, task: str) -> ToolResult:
        # Real execution happens through the async special-case in execute() so the
        # nested agent loop can await the brain. This sync stub exists to satisfy the
        # manifest/handler contract and is never reached via normal dispatch.
        if self.subagent_runner is None:
            return ToolResult(False, "The sub-agent runner isn't active right now, Boss.")
        return ToolResult(
            False,
            "This sub-agent gets executed through its dedicated path, keep waiting, Boss.",
        )

    @staticmethod
    def _git_run(action: str, path: str, message: str, mutate: bool) -> ToolResult:
        action = (action or "").strip().lower()
        read_actions = {"status", "diff", "log", "branch"}
        write_actions = {"add", "commit", "push", "pull", "fetch"}
        valid = read_actions | write_actions
        if action not in valid:
            return ToolResult(False, f"The git action must be one of {', '.join(sorted(valid))}, Boss.")

        working_directory = None
        if path:
            try:
                working_directory = Path(os.path.expandvars(path)).expanduser().resolve()
            except OSError:
                return ToolResult(False, "That repository path is invalid.")
            if not working_directory.is_dir() or not TaskAgent._is_local_path(working_directory):
                return ToolResult(False, "The repository must be inside a folder under your user profile.")

        git_path = shutil.which("git")
        if not git_path:
            return ToolResult(False, "Git is not installed on this machine, Boss.")

        args = [git_path, "-C", str(working_directory) if working_directory else "."]
        if action == "status":
            args += ["status", "--short", "--branch"]
        elif action == "diff":
            args += ["diff", "--stat"]
        elif action == "log":
            args += ["log", "--oneline", "-15"]
        elif action == "branch":
            args += ["branch", "-vv"]
        elif action == "add":
            args += ["add", "-A"]
        elif action == "commit":
            msg = (message or "").strip()
            if not msg:
                return ToolResult(False, "A commit message is required for a git commit, Boss.")
            args += ["commit", "-m", msg]
        elif action == "push":
            args += ["push"]
        elif action == "pull":
            args += ["pull", "--ff-only"]
        elif action == "fetch":
            args += ["fetch", "--all"]

        try:
            process = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=90,
                cwd=str(working_directory) if working_directory else None,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(False, f"The git {action} timed out after 90 seconds, Boss.")
        except Exception as exc:
            return ToolResult(False, f"Could not run git: {exc}")

        output = (process.stdout or "").strip()
        err = (process.stderr or "").strip()
        ok = process.returncode == 0
        lines = []
        if output:
            lines.append(output)
        if err:
            lines.append(err)
        text = "\n".join(lines).strip()
        if not text:
            text = f"git {action} completed with no output."
        return ToolResult(
            ok,
            text[:6000],
            data={"action": action, "ok": ok, "returncode": process.returncode},
        )

    @staticmethod
    def _weather(location: str) -> ToolResult:
        if location.strip() == "?":
            location = ""
        target = quote(location) if location else ""
        response = requests.get(
            f"https://wttr.in/{target}?format=j1",
            timeout=10,
            headers={"User-Agent": "FRIDAY-local-assistant"},
        )
        response.raise_for_status()
        payload = response.json()
        current = payload["current_condition"][0]
        description = current["weatherDesc"][0]["value"]
        place = location or "your current area"
        message = (
            f"In {place}, it's {current['temp_C']} degrees Celsius with {description.lower()}. "
            f"It feels like {current['FeelsLikeC']} degrees, with {current['humidity']} percent humidity, Boss."
        )
        return ToolResult(True, message)

    @staticmethod
    def _find_files(query: str) -> ToolResult:
        if len(query) < 2:
            return ToolResult(False, "Please give me at least two characters to search for, Boss.")
        matches: list[str] = []
        skipped = {".git", "node_modules", "AppData", "$Recycle.Bin"}
        for root in config.TASK_SEARCH_ROOTS:
            if not root.exists():
                continue
            for current, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d not in skipped and not d.startswith(".")]
                for filename in files:
                    if query.lower() in filename.lower():
                        matches.append(str(Path(current) / filename))
                        if len(matches) >= 25:
                            break
                if len(matches) >= 25:
                    break
            if len(matches) >= 25:
                break
        if not matches:
            return ToolResult(False, f"I couldn't find a file matching {query}, Boss.")
        message = f"Found {len(matches)} matching file(s):\n" + "\n".join(matches)
        speech = f"I found {len(matches)} matching file(s), Boss. They're listed in the HUD."
        return ToolResult(True, message, speech=speech, data={"paths": matches})

    @staticmethod
    def _list_directory(path: str) -> ToolResult:
        try:
            target = Path(os.path.expandvars(path)).expanduser().resolve()
        except Exception:
            return ToolResult(False, "That folder path is invalid.")
        if not TaskAgent._is_local_path(target):
            return ToolResult(False, "Folder access is limited to your user profile.")
        if not target.exists() or not target.is_dir():
            return ToolResult(False, f"That folder does not exist: {target}")
        try:
            items = sorted(
                target.iterdir(),
                key=lambda item: (not item.is_dir(), item.name.lower()),
            )
        except OSError as exc:
            return ToolResult(False, f"I couldn't list that folder: {exc}")
        if not items:
            return ToolResult(True, f"{target} is empty.", data={"path": str(target), "entries": []})

        visible = items[:100]
        lines = [f"[folder] {item.name}" if item.is_dir() else item.name for item in visible]
        truncated = len(items) > len(visible)
        message = f"Contents of {target} ({len(items)} item(s)):\n" + "\n".join(lines)
        if truncated:
            message += f"\n... and {len(items) - len(visible)} more item(s)."
        entries = [
            {
                "name": item.name,
                "type": "folder" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
            }
            for item in visible
        ]
        return ToolResult(
            True,
            message,
            speech=f"I found {len(items)} items in {target.name}.",
            data={"path": str(target), "entries": entries, "truncated": truncated},
        )

    @staticmethod
    def _file_info(path: str) -> ToolResult:
        try:
            target = Path(os.path.expandvars(path)).expanduser().resolve()
            if not TaskAgent._is_local_path(target):
                return ToolResult(False, "Path access is limited to your user profile.")
            stat = target.stat()
        except FileNotFoundError:
            return ToolResult(False, f"That path does not exist: {path}")
        except OSError as exc:
            return ToolResult(False, f"I couldn't inspect that path: {exc}")
        kind = "folder" if target.is_dir() else "file"
        modified = datetime.datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds")
        size = None if target.is_dir() else stat.st_size
        message = f"{target}\nType: {kind}\nModified: {modified}"
        if size is not None:
            message += f"\nSize: {size} bytes"
        return ToolResult(
            True,
            message,
            data={"path": str(target), "type": kind, "size": size, "modified": modified},
        )

    @staticmethod
    def _search_text(root: str, query: str, file_suffix: str = "") -> ToolResult:
        try:
            directory = Path(os.path.expandvars(root)).expanduser().resolve()
        except OSError:
            return ToolResult(False, "That search directory is invalid.")
        if not TaskAgent._is_local_path(directory):
            return ToolResult(False, "Text search is limited to your user profile.")
        if not directory.is_dir() or not query:
            return ToolResult(False, "Text search requires an existing directory and query.")
        suffix = file_suffix.strip().lower()
        if suffix and not suffix.startswith("."):
            suffix = "." + suffix
        skipped = {".git", ".venv", "node_modules", "__pycache__", "dist", "build"}
        matches: list[dict] = []
        scanned = 0
        try:
            for current, dirs, files in os.walk(directory):
                dirs[:] = [name for name in dirs if name not in skipped]
                for filename in files:
                    path = Path(current) / filename
                    if suffix and path.suffix.lower() != suffix:
                        continue
                    if path.suffix.lower() not in {
                        ".py", ".js", ".ts", ".tsx", ".java", ".c", ".cpp", ".h",
                        ".html", ".css", ".json", ".yaml", ".yml", ".toml", ".ini",
                        ".md", ".txt", ".bat", ".ps1", ".sh", ".sql",
                    }:
                        continue
                    scanned += 1
                    if scanned > 3000 or path.stat().st_size > 1024 * 1024:
                        continue
                    for line_number, line in enumerate(
                        path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
                    ):
                        if query.lower() in line.lower():
                            matches.append(
                                {"path": str(path), "line": line_number, "text": line[:500]}
                            )
                            if len(matches) >= 100:
                                break
                    if len(matches) >= 100:
                        break
                if len(matches) >= 100 or scanned > 3000:
                    break
        except OSError as exc:
            return ToolResult(False, f"Text search failed: {exc}")
        if not matches:
            return ToolResult(False, f"No text matching {query!r} was found under {directory}.")
        lines = [f"{item['path']}:{item['line']}: {item['text']}" for item in matches]
        return ToolResult(
            True,
            f"Found {len(matches)} text match(es):\n" + "\n".join(lines),
            data={"matches": matches, "scanned_files": scanned},
        )

    def _replace_in_file(self, path: str, old_string: str, new_string: str) -> ToolResult:
        try:
            target = Path(os.path.expandvars(path)).expanduser().resolve()
        except OSError:
            return ToolResult(False, "That file path is invalid.")
        if not self._is_local_path(target) or self._is_protected(target) or not target.is_file():
            return ToolResult(False, "That file is missing or protected.")
        if not old_string or old_string == new_string:
            return ToolResult(False, "The replacement must contain a real, non-empty change.")
        try:
            original = target.read_text(encoding="utf-8")
        except OSError as exc:
            return ToolResult(False, f"I couldn't read that file: {exc}")
        occurrences = original.count(old_string)
        if occurrences != 1:
            return ToolResult(False, f"Expected one exact match but found {occurrences}.")
        updated = original.replace(old_string, new_string, 1)
        if target.suffix.lower() == ".py":
            try:
                ast.parse(updated)
            except SyntaxError as exc:
                return ToolResult(False, f"The replacement has invalid Python syntax: {exc}")
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = target.with_suffix(target.suffix + f".{stamp}.bak")
        temporary = target.with_suffix(target.suffix + f".{uuid.uuid4().hex}.tmp")
        try:
            shutil.copy2(target, backup)
            temporary.write_text(updated, encoding="utf-8")
            os.replace(temporary, target)
        except OSError as exc:
            return ToolResult(False, f"I couldn't apply the replacement: {exc}")
        finally:
            temporary.unlink(missing_ok=True)
        return ToolResult(
            True,
            f"Updated {target}; backup saved to {backup.name}.",
            data={"path": str(target), "backup": str(backup)},
        )

    def _create_directory(self, path: str) -> ToolResult:
        try:
            target = Path(os.path.expandvars(path)).expanduser().resolve()
        except OSError:
            return ToolResult(False, "That folder path is invalid.")
        if not self._is_local_path(target) or self._is_protected(target):
            return ToolResult(False, "That destination is protected.")
        if target.exists():
            return ToolResult(target.is_dir(), f"{target} already exists.")
        try:
            target.mkdir(parents=True)
        except OSError as exc:
            return ToolResult(False, f"I couldn't create that folder: {exc}")
        return ToolResult(True, f"Created folder {target}.", data={"path": str(target)})

    def _copy_path(self, source: str, destination: str) -> ToolResult:
        try:
            src = Path(os.path.expandvars(source)).expanduser().resolve()
            dest = Path(os.path.expandvars(destination)).expanduser().resolve()
        except OSError:
            return ToolResult(False, "The source or destination path is invalid.")
        if not self._is_local_path(src) or not self._is_local_path(dest):
            return ToolResult(False, "File operations are limited to your user profile.")
        if not src.exists():
            return ToolResult(False, f"The source does not exist: {src}")
        if self._is_protected(dest):
            return ToolResult(False, "That destination is protected.")
        if dest.exists():
            return ToolResult(False, f"The destination already exists: {dest}")
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dest)
            else:
                shutil.copy2(src, dest)
        except OSError as exc:
            return ToolResult(False, f"I couldn't copy that path: {exc}")
        return ToolResult(
            True,
            f"Copied {src} to {dest}.",
            data={"source": str(src), "destination": str(dest)},
        )

    def _move_path(self, source: str, destination: str) -> ToolResult:
        try:
            src = Path(os.path.expandvars(source)).expanduser().resolve()
            dest = Path(os.path.expandvars(destination)).expanduser().resolve()
        except OSError:
            return ToolResult(False, "The source or destination path is invalid.")
        if not self._is_local_path(src) or not self._is_local_path(dest):
            return ToolResult(False, "File operations are limited to your user profile.")
        if not src.exists():
            return ToolResult(False, f"The source does not exist: {src}")
        if self._is_protected(src) or self._is_protected(dest):
            return ToolResult(False, "The source or destination is protected.")
        if dest.exists():
            return ToolResult(False, f"The destination already exists: {dest}")
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
        except OSError as exc:
            return ToolResult(False, f"I couldn't move that path: {exc}")
        return ToolResult(
            True,
            f"Moved {src} to {dest}.",
            data={"source": str(src), "destination": str(dest)},
        )

    @staticmethod
    def _edit_own_file(path: str, old_string: str, new_string: str) -> ToolResult:
        try:
            target = Path(os.path.expandvars(path)).expanduser().resolve()
        except OSError:
            return ToolResult(False, "That source path is invalid.")
        base = config.BASE_DIR.resolve()
        if base not in target.parents or not target.is_file():
            return ToolResult(False, "Self-editing is restricted to existing FRIDAY source files.")
        if target.suffix.lower() not in {
            ".py", ".js", ".html", ".css", ".json", ".txt", ".md", ".bat"
        }:
            return ToolResult(False, "That FRIDAY file type is not editable through this tool.")
        if not old_string or old_string == new_string:
            return ToolResult(False, "The replacement must contain a real, non-empty change.")
        try:
            original = target.read_text(encoding="utf-8")
        except OSError as exc:
            return ToolResult(False, f"I couldn't read that source file: {exc}")
        occurrences = original.count(old_string)
        if occurrences != 1:
            return ToolResult(
                False,
                f"The exact original text must occur once; I found {occurrences} matches.",
            )
        updated = original.replace(old_string, new_string, 1)
        if target.suffix.lower() == ".py":
            try:
                ast.parse(updated)
            except SyntaxError as exc:
                return ToolResult(False, f"The proposed self-edit has invalid Python syntax: {exc}")
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = target.with_suffix(target.suffix + f".{stamp}.bak")
        temporary = target.with_suffix(target.suffix + f".{uuid.uuid4().hex}.tmp")
        try:
            shutil.copy2(target, backup)
            temporary.write_text(updated, encoding="utf-8")
            os.replace(temporary, target)
        except OSError as exc:
            return ToolResult(False, f"I couldn't apply the self-edit: {exc}")
        finally:
            temporary.unlink(missing_ok=True)
        return ToolResult(
            True,
            f"Updated FRIDAY source file {target}; backup saved to {backup.name}.",
            data={"path": str(target), "backup": str(backup)},
        )

    @staticmethod
    def _current_time() -> ToolResult:
        now = datetime.datetime.now().astimezone()
        rendered = now.isoformat(timespec="seconds")
        return ToolResult(
            True,
            f"Current local date and time: {rendered}",
            data={"iso": rendered, "timezone": str(now.tzinfo)},
        )

    @staticmethod
    def _tile_windows() -> ToolResult:
        try:
            import pygetwindow as gw
            windows = gw.getWindowsWithTitle("")
            visible = [w for w in windows if w.visible and not w.isMinimized]
            if not visible:
                return ToolResult(False, "No visible windows found, Boss.")
            screens = gw.workmonitor().monitors if hasattr(gw, 'workmonitor') else None
            cols = max(1, int(len(visible) ** 0.5) + 1)
            rows = (len(visible) + cols - 1) // cols
            sw, sh = 1920, 1080
            try:
                import ctypes
                user32 = ctypes.windll.user32
                sw = user32.GetSystemMetrics(0)
                sh = user32.GetSystemMetrics(1)
            except Exception:
                pass
            ww = sw // cols
            wh = sh // rows
            for i, win in enumerate(visible):
                col = i % cols
                row = i // cols
                try:
                    win.moveTo(col * ww, row * wh)
                    win.resizeTo(ww, wh)
                except Exception:
                    pass
            return ToolResult(True, f"Tiled {len(visible)} window(s) in a {cols}x{rows} grid, Boss.")
        except ImportError:
            return ToolResult(False, "Window management requires pygetwindow, Boss.")
        except Exception as e:
            return ToolResult(False, f"Could not tile windows: {e}")

    @staticmethod
    def _maximize_window() -> ToolResult:
        try:
            import pygetwindow as gw
            focused = gw.getActiveWindow()
            if focused:
                focused.maximize()
                return ToolResult(True, f"Maximized: {focused.title}, Boss.")
            return ToolResult(False, "No active window found, Boss.")
        except ImportError:
            return ToolResult(False, "Window management requires pygetwindow, Boss.")
        except Exception as e:
            return ToolResult(False, f"Could not maximize: {e}")

    @staticmethod
    def _minimize_window() -> ToolResult:
        try:
            import pygetwindow as gw
            focused = gw.getActiveWindow()
            if focused:
                focused.minimize()
                return ToolResult(True, f"Minimized: {focused.title}, Boss.")
            return ToolResult(False, "No active window found, Boss.")
        except ImportError:
            return ToolResult(False, "Window management requires pygetwindow, Boss.")
        except Exception as e:
            return ToolResult(False, f"Could not minimize: {e}")

    @staticmethod
    def _system_health() -> ToolResult:
        try:
            cpu = psutil.cpu_percent(interval=1)
            ram = psutil.virtual_memory()
            disk = psutil.disk_usage(str(Path.home().anchor) or "/")
            temp_info = ""
            try:
                temps = psutil.sensors_temperatures()
                if temps:
                    for name, entries in temps.items():
                        if entries:
                            temp_info = f", Temp: {entries[0].current}C"
            except Exception:
                pass
            gpu_info = ""
            try:
                import subprocess
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    parts = result.stdout.strip().split(", ")
                    if len(parts) >= 3:
                        gpu_info = f", GPU: {parts[0]}% ({parts[1]}/{parts[2]} MB)"
            except Exception:
                pass
            message = (
                f"CPU: {cpu}% | RAM: {ram.percent}% ({ram.used // (1024**3):.1f}/{ram.total // (1024**3):.1f} GB) | "
                f"Disk: {disk.percent}% ({disk.free // (1024**3):.1f} GB free){temp_info}{gpu_info}"
            )
            return ToolResult(True, message, speech=f"System health: CPU {cpu}%, RAM {ram.percent}%, Boss.")
        except Exception as e:
            return ToolResult(False, f"Could not check system health: {e}")

    @staticmethod
    def _list_processes() -> ToolResult:
        try:
            processes = list(psutil.process_iter(["pid", "name", "memory_percent"]))
            for proc in processes:
                try:
                    proc.cpu_percent(None)  # prime the CPU counters
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            time.sleep(0.3)
            rows = []
            for proc in processes:
                try:
                    cpu = proc.cpu_percent(None)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                mem = proc.info.get("memory_percent") or 0.0
                name = proc.info.get("name") or f"pid{proc.pid}"
                rows.append((name, cpu, mem))
            rows.sort(key=lambda row: (row[1], row[2]), reverse=True)
            top = rows[:10]
            if not top:
                return ToolResult(True, "No significant processes running, Boss.")
            message = "Top processes:\n" + "\n".join(
                f"- {name} (CPU: {cpu:.1f}%, RAM: {mem:.1f}%)"
                for name, cpu, mem in top
            )
            return ToolResult(True, message, speech=f"Showing top {len(top)} processes, Boss.")
        except Exception as e:
            return ToolResult(False, f"Could not list processes: {e}")

    @staticmethod
    def _screenshot() -> ToolResult:
        import mss
    
        config.CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
        output = config.CAPTURES_DIR / time.strftime("friday-%Y%m%d-%H%M%S.png")
        with mss.mss() as capture:
            capture.shot(output=str(output))
        return ToolResult(
            True,
            f"Screenshot saved to {output}",
            speech="Screenshot captured, Boss.",
            data={"path": str(output)},
        )

    def _vision_screen(self) -> ToolResult:
        try:
            frame = _LOCAL_VISION.capture_screen()
            path = _LOCAL_VISION.save_frame(frame, f"vision_screen_{uuid.uuid4().hex}.png")
            if self.vision_analyzer is None:
                return ToolResult(False, "The screen was captured, but local vision is unavailable.")
            analysis = self.vision_analyzer(
                str(path), "Describe what is visible on this screen. Read important text accurately."
            )
            return ToolResult(
                True,
                analysis,
                speech="I analyzed the current screen. The details are in the HUD.",
                data={"path": str(path), "analysis": analysis}
            )
        except Exception as e:
            return ToolResult(False, f"Vision error: {e}")

    def _vision_camera(self) -> ToolResult:
        try:
            frame = _LOCAL_VISION.capture_camera()
            if frame is None:
                return ToolResult(False, "Camera not found or unavailable, Boss.")
            path = _LOCAL_VISION.save_frame(frame, f"vision_cam_{uuid.uuid4().hex}.png")
            if self.vision_analyzer is None:
                return ToolResult(False, "The camera frame was captured, but local vision is unavailable.")
            analysis = self.vision_analyzer(
                str(path), "Describe the camera image accurately. Do not guess beyond visible evidence."
            )
            return ToolResult(
                True,
                analysis,
                speech="I analyzed the camera image. The details are in the HUD.",
                data={"path": str(path), "analysis": analysis}
            )
        except Exception as e:
            return ToolResult(False, f"Vision error: {e}")

    _IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}

    @staticmethod
    def _looks_like_image_path(value: str) -> bool:
        """True if the captured phrase points at an image file by path."""
        text = value.strip(" \"'.!?")
        if not text or len(text) > 300:
            return False
        expanded = os.path.expandvars(text)
        suffix = Path(expanded).suffix.lower()
        if suffix in TaskAgent._IMAGE_SUFFIXES:
            return True
        if re.search(r"[a-zA-Z]:[\\/]|[\\/]", text) and suffix:
            return suffix in TaskAgent._IMAGE_SUFFIXES or suffix in {
                ".heic", ".tif", ".tiff",
            }
        return False

    def _inspect_image(self, path: str, prompt: str = "Describe what is inside this image accurately.") -> ToolResult:
        try:
            target = Path(os.path.expandvars(path)).expanduser().resolve()
        except Exception:
            return ToolResult(False, "That file path isn't valid, Boss.")
        if not self._is_local_path(target):
            return ToolResult(False, "Image access is limited to your user profile, Boss.")
        if not target.exists() or not target.is_file():
            return ToolResult(False, f"I couldn't find that image at {path}, Boss.")
        if target.suffix.lower() not in self._IMAGE_SUFFIXES:
            return ToolResult(False, f"{target.name} is not a supported image file, Boss.")
        if target.stat().st_size > 15 * 1024 * 1024:
            return ToolResult(False, "That image is over 15 MB — it's too large to analyze, Boss.")
        if self.vision_analyzer is None:
            return ToolResult(False, "Local vision is unavailable right now, Boss.")
        try:
            analysis = self.vision_analyzer(
                str(target),
                (prompt or "Describe what is inside this image accurately."),
            )
        except Exception as exc:
            return ToolResult(False, f"Vision error: {exc}")
        if not analysis:
            return ToolResult(False, "I couldn't make out what's in that image, Boss.")
        return ToolResult(
            True,
            analysis,
            speech="I've looked at the image. The details are in the HUD.",
            data={"path": str(target), "analysis": analysis},
        )

    def _self_edit(self, file_path: str) -> ToolResult:
        # This is the 'Read' part of the edit cycle
        try:
            # If file_path is empty, the AI needs to provide it in a second step
            # but for now we'll allow it to read the file to understand the context
            if not file_path:
                return ToolResult(False, "Please specify which file needs fixing, Boss.")

            absolute_path = Path(os.path.expandvars(file_path)).expanduser().resolve()
            if not self._is_local_path(absolute_path):
                return ToolResult(False, "File access is limited to your user profile, Boss.")
            if not absolute_path.exists():
                return ToolResult(False, f"File {file_path} not found, Boss.")

            with open(absolute_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            return ToolResult(
                True, 
                f"Content of {file_path} loaded. Please provide the 'old_string' and 'new_string' to apply the fix.",
                speech=f"I've analyzed {file_path}, Boss. Tell me exactly what to change.",
                data={"content": content}
            )
        except Exception as e:
            return ToolResult(False, f"Error reading file: {e}")

    def _apply_fix(self, old_string: str, new_string: str, file_path: str) -> ToolResult:
        try:
            absolute_path = Path(os.path.expandvars(file_path)).expanduser().resolve()
        except OSError:
            return ToolResult(False, "That file path is invalid, Boss.")
        if not self._is_local_path(absolute_path) or self._is_protected(absolute_path):
            return ToolResult(False, "Fixes are limited to files inside your user profile, Boss.")
        if absolute_path.suffix.lower() != ".py":
            return ToolResult(False, "Apply-fix only supports Python source files, Boss.")
        if not absolute_path.exists():
            return ToolResult(False, "Target file not found, Boss.")

        try:
            with open(absolute_path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError as exc:
            return ToolResult(False, f"Error reading file: {exc}")

        if old_string not in content:
            return ToolResult(False, "I couldn't find the exact original code to replace, Boss. Please be more precise.")

        new_content = content.replace(old_string, new_string)

        # SYNTAX CHECK: Prevent F.R.I.D.A.Y. from breaking herself
        try:
            ast.parse(new_content)
        except SyntaxError as e:
            return ToolResult(False, f"I cannot apply this fix because it contains a Python syntax error: {e}")

        # Backup existing file
        backup_path = absolute_path.with_suffix(".bak")
        try:
            shutil.copy(absolute_path, backup_path)
            with open(absolute_path, "w", encoding="utf-8") as f:
                f.write(new_content)
        except OSError as e:
            return ToolResult(False, f"Error applying fix: {e}")

        return ToolResult(
            True,
            f"Fix applied successfully to {file_path}. I've created a backup at {backup_path}.",
            speech="I've patched the code and verified the syntax, Boss. Systems are restored."
        )

    @staticmethod
    def _volume(action: str) -> ToolResult:
        keys = {"up": 0xAF, "down": 0xAE, "mute": 0xAD}
        key = keys[action]
        presses = 5 if action in {"up", "down"} else 1
        for _ in range(presses):
            ctypes.windll.user32.keybd_event(key, 0, 0, 0)
            ctypes.windll.user32.keybd_event(key, 0, 2, 0)
        word = "toggled" if action == "mute" else f"turned {action}"
        return ToolResult(True, f"Volume {word}, Boss.")

    @staticmethod
    def _read_clipboard() -> ToolResult:
        process = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if process.returncode != 0:
            return ToolResult(False, "I couldn't read the clipboard, Boss.")
        content = process.stdout.strip()
        if not content:
            return ToolResult(True, "The clipboard is empty, Boss.")
        return ToolResult(
            True,
            f"Clipboard contents:\n{content[:4000]}",
            speech="I've displayed the clipboard contents, Boss.",
        )

    @staticmethod
    def _type_text(text: str) -> ToolResult:
        import pyautogui

        time.sleep(3)
        pyautogui.write(text, interval=0.015)
        return ToolResult(True, "Text entered into the active window, Boss.")

    @staticmethod
    def _close_app(app_id: str) -> ToolResult:
        process = subprocess.run(
            ["taskkill.exe", "/IM", _PROCESS_NAMES[app_id]],
            capture_output=True,
            text=True,
        )
        if process.returncode != 0:
            return ToolResult(False, f"I couldn't close {_APP_LABELS[app_id]}, Boss.")
        return ToolResult(True, f"Closed {_APP_LABELS[app_id]}, Boss.")

    @staticmethod
    def _power(action: str) -> ToolResult:
        if action == "signout":
            subprocess.Popen(["shutdown.exe", "/l", "/t", "10"])
            return ToolResult(True, "Signing out of Windows in 10 seconds, Boss. Run shutdown /a to abort.")
        if action == "shutdown":
            subprocess.Popen(["shutdown.exe", "/s", "/t", "10", "/c", "Scheduled by FRIDAY"])
            return ToolResult(True, "Shutdown scheduled in 10 seconds, Boss. Run shutdown /a to abort.")
        if action == "restart":
            subprocess.Popen(["shutdown.exe", "/r", "/t", "10", "/c", "Scheduled by FRIDAY"])
            return ToolResult(True, "Restart scheduled in 10 seconds, Boss. Run shutdown /a to abort.")
        subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        return ToolResult(True, "Putting the computer to sleep, Boss.")

    @staticmethod
    def _recycle_file(path: str) -> ToolResult:
        raw = Path(os.path.expandvars(path)).expanduser()
        if not raw.is_absolute():
            return ToolResult(False, "For safety, file removal requires a complete path, Boss.")
        target = raw.resolve()
        home = Path.home().resolve()
        protected_trees = [
            config.BASE_DIR.resolve(),
            Path(os.environ.get("WINDIR", r"C:\Windows")).resolve(),
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")).resolve(),
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")).resolve(),
        ]
        if target.anchor == str(target) or target == home or any(
            target == root or root in target.parents for root in protected_trees
        ):
            return ToolResult(False, "That path is protected and cannot be removed, Boss.")
        if not target.exists():
            return ToolResult(False, "That file does not exist, Boss.")
        if not target.is_file():
            return ToolResult(False, "Folder removal is disabled, Boss.")
        from send2trash import send2trash

        send2trash(str(target))
        return ToolResult(True, f"Moved {target.name} to the Recycle Bin, Boss.")

    # ============ GENERAL-PURPOSE HANDLERS ============

    @staticmethod
    def _protected_trees() -> list[Path]:
        home = Path.home().resolve()
        return [
            config.BASE_DIR.resolve(),  # the friday-kit itself stays read-only for writes
            Path(os.environ.get("WINDIR", r"C:\Windows")).resolve(),
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")).resolve(),
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")).resolve(),
        ]

    @staticmethod
    def _is_protected(target: Path) -> bool:
        home = Path.home().resolve()
        if target.anchor == str(target) or target == home:
            return True
        for root in TaskAgent._protected_trees():
            if target == root or root in target.parents:
                return True
        return False

    @staticmethod
    def _is_local_path(target: Path) -> bool:
        """General file tools stay inside the current user's filesystem tree."""
        home = Path.home().resolve()
        return target == home or home in target.parents

    @staticmethod
    def _resolve_user_path(path: str) -> Path | None:
        """Expand a model-supplied path; bare relative names anchor at the profile."""
        try:
            candidate = Path(os.path.expandvars(str(path))).expanduser()
            if not candidate.is_absolute():
                candidate = Path.home() / candidate
            return candidate.resolve()
        except Exception:
            return None

    @staticmethod
    def _run_shell(command: str, cwd: str = "") -> ToolResult:
        if is_blocked_command(command):
            return ToolResult(False, "I blocked that command — it's too destructive to run, Boss.")
        working_directory = None
        if cwd:
            try:
                working_directory = Path(os.path.expandvars(cwd)).expanduser().resolve()
            except OSError:
                return ToolResult(False, "The command working directory is invalid.")
            if not working_directory.is_dir() or not TaskAgent._is_local_path(working_directory):
                return ToolResult(False, "Commands may only run inside a folder under your user profile.")
        try:
            process = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(working_directory) if working_directory else None,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(False, "The command timed out after 60 seconds, Boss.")
        except Exception as exc:
            return ToolResult(False, f"Could not run the command: {exc}")
        output = (process.stdout or "").strip()
        err = (process.stderr or "").strip()
        ok = process.returncode == 0
        if not output and not err:
            message = "The command completed with no output." if ok else f"The command failed with exit code {process.returncode}."
            return ToolResult(ok, message, data={"exit_code": process.returncode})
        sections = []
        if output:
            sections.append("Output:\n" + output[:6000])
        if err:
            sections.append("Error output:\n" + err[:4000])
        return ToolResult(
            ok,
            "\n\n".join(sections),
            data={"stdout": output[:6000], "stderr": err[:4000], "exit_code": process.returncode},
        )

    def _run_background(self, command: str, cwd: str = "", label: str = "") -> ToolResult:
        """Start a detached background subagent task; returns immediately."""
        if self.background is None:
            return ToolResult(False, "Background task support is unavailable, Boss.")
        working_directory = None
        if cwd:
            working_directory = self._resolve_user_path(cwd)
            if (
                working_directory is None
                or not working_directory.is_dir()
                or not self._is_local_path(working_directory)
            ):
                return ToolResult(
                    False, "Background commands may only run inside a folder under your user profile, Boss."
                )
        try:
            task = self.background.start(
                command,
                cwd=str(working_directory) if working_directory else "",
                label=label,
            )
        except ValueError as exc:
            return ToolResult(False, str(exc))
        except OSError as exc:
            return ToolResult(False, f"I couldn't start that background task: {exc}")
        return ToolResult(
            True,
            f"Started background task {task.id[:8]} ({task.label or command[:80]}). "
            "It runs detached; I'll notify you here when it finishes, Boss.",
            speech="Background task started, Boss.",
            data={"task_id": task.id, "log": str(task.output_file), "state": task.state},
        )

    def _background_status(self, task_id: str = "") -> ToolResult:
        if self.background is None:
            return ToolResult(False, "Background task support is unavailable, Boss.")
        tasks = self.background.status(task_id)
        if not tasks:
            if task_id:
                return ToolResult(False, f"I couldn't find a background task matching {task_id}, Boss.")
            return ToolResult(True, "There are no background tasks yet, Boss.")
        lines = []
        for task in tasks:
            header = (
                f"[{task['id'][:8]}] {task['state']}"
                + (f" (exit {task['exit_code']})" if task['exit_code'] is not None else "")
                + f" — {task['label'] or task['command'][:80]}"
            )
            tail = (task.get("output_tail") or "").strip()
            lines.append(header + (f"\n{tail}" if tail else ""))
        message = "\n\n".join(lines)
        running = sum(1 for task in tasks if task["state"] == "running")
        summary = f"{len(tasks)} background task(s), {running} still running."
        return ToolResult(True, f"{summary}\n{message}", data={"tasks": tasks})

    def _read_file(self, path: str) -> ToolResult:
        target = TaskAgent._resolve_user_path(path)
        if target is None:
            return ToolResult(False, "That file path isn't valid, Boss.")
        if not self._is_local_path(target):
            return ToolResult(False, "File access is limited to your user profile, Boss.")
        if not target.exists() or not target.is_file():
            return ToolResult(False, f"I couldn't find that file at {path}, Boss.")
        if target.stat().st_size > 1024 * 1024:
            return ToolResult(False, "That file is over 1 MB — I can't read it all, Boss.")
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return ToolResult(False, f"I couldn't read that file: {exc}")
        limited = content[:12000]
        message = f"Contents of {target.name}:\n```\n{limited}\n```"
        if len(content) > 12000:
            message += "\n... (truncated)"
        return ToolResult(
            True,
            message,
            speech=f"I've opened {target.name}, Boss.",
            data={"path": str(target), "content": limited, "truncated": len(content) > len(limited)},
        )

    def _write_file(self, path: str, content: str) -> ToolResult:
        target = TaskAgent._resolve_user_path(path)
        if target is None:
            return ToolResult(False, "That file path isn't valid, Boss.")
        if target.suffix.lower() == ".py" and content.strip():
            try:
                ast.parse(content)
            except SyntaxError as exc:
                return ToolResult(
                    False,
                    f"I refused to write that — the Python has a syntax error ({exc}), Boss.",
                )
        if not self._is_local_path(target) or self._is_protected(target):
            return ToolResult(False, "That path is protected — I won't write there, Boss.")
        try:
            existed = target.exists()
            target.parent.mkdir(parents=True, exist_ok=True)
            if existed:
                backup = target.with_suffix(target.suffix + ".bak")
                shutil.copy(target, backup)
            target.write_text(content, encoding="utf-8")
        except Exception as exc:
            return ToolResult(False, f"I couldn't write that file: {exc}")
        done = "updated" if existed else "created"
        return ToolResult(
            True,
            f"{done.title()} {target}, Boss.",
            speech=f"File {done}, Boss.",
            data={"path": str(target)},
        )

    @staticmethod
    def _safe_eval(node, depth: int = 0):
        if depth > 24:
            raise ValueError("Expression is too deeply nested")
        ops = {
            ast.Add: lambda a, b: a + b,
            ast.Sub: lambda a, b: a - b,
            ast.Mult: lambda a, b: a * b,
            ast.Div: lambda a, b: a / b,
            ast.FloorDiv: lambda a, b: a // b,
            ast.Mod: lambda a, b: a % b,
            ast.Pow: lambda a, b: a ** b,
            ast.USub: lambda a: -a,
            ast.UAdd: lambda a: +a,
        }
        if isinstance(node, ast.Expression):
            return TaskAgent._safe_eval(node.body, depth + 1)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or isinstance(node.value, (int, float)):
                if abs(node.value) > 10**100:
                    raise ValueError("Number is too large")
                return node.value
            raise ValueError("Unsupported constant")
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            left = TaskAgent._safe_eval(node.left, depth + 1)
            right = TaskAgent._safe_eval(node.right, depth + 1)
            if isinstance(node.op, ast.Pow) and abs(right) > 1000:
                raise ValueError("Exponent is too large")
            result = ops[type(node.op)](left, right)
            if isinstance(result, (int, float)) and abs(result) > 10**1000:
                raise ValueError("Result is too large")
            return result
        if isinstance(node, ast.UnaryOp) and type(node.op) in ops:
            return ops[type(node.op)](TaskAgent._safe_eval(node.operand, depth + 1))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn = node.func.id.lower()
            nargs = len(node.args)
            table = {
                "sin": lambda: math.sin(TaskAgent._safe_eval(node.args[0], depth + 1)),
                "cos": lambda: math.cos(TaskAgent._safe_eval(node.args[0], depth + 1)),
                "tan": lambda: math.tan(TaskAgent._safe_eval(node.args[0], depth + 1)),
                "sqrt": lambda: math.sqrt(TaskAgent._safe_eval(node.args[0], depth + 1)),
                "abs": lambda: abs(TaskAgent._safe_eval(node.args[0], depth + 1)),
                "log": lambda: math.log(TaskAgent._safe_eval(node.args[0], depth + 1)),
                "exp": lambda: math.exp(TaskAgent._safe_eval(node.args[0], depth + 1)),
                "floor": lambda: math.floor(TaskAgent._safe_eval(node.args[0], depth + 1)),
                "ceil": lambda: math.ceil(TaskAgent._safe_eval(node.args[0], depth + 1)),
                "round": lambda: round(TaskAgent._safe_eval(node.args[0], depth + 1)),
                "factorial": lambda: math.factorial(TaskAgent._factorial_arg(node.args[0], depth)),
            }
            if fn in table and nargs == 1:
                return table[fn]()
            raise ValueError("Unsupported function")
        if isinstance(node, ast.Name):
            name = node.id.lower()
            if name == "pi":
                return math.pi
            if name == "e":
                return math.e
            raise ValueError("Unsupported name")
        raise ValueError("Unsupported expression")

    @staticmethod
    def _factorial_arg(node, depth: int) -> int:
        value = TaskAgent._safe_eval(node, depth + 1)
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 1000:
            raise ValueError("Factorial requires an integer from 0 to 1000")
        return value

    def _math(self, expression: str) -> ToolResult:
        expr = expression.replace("^", "**")
        try:
            tree = ast.parse(expr, mode="eval")
            if sum(1 for _ in ast.walk(tree)) > 64:
                raise ValueError("Expression is too complex")
            result = self._safe_eval(tree)
        except Exception as exc:
            return ToolResult(False, f"I couldn't compute that: {exc}")
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        return ToolResult(True, f"{expression.strip()} = {result}", speech=f"Calculation complete, Boss.")

    @staticmethod
    def _validate_public_url(url: str) -> str | None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            return "I can only fetch public http/https pages."
        try:
            addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443)
            for address in addresses:
                ip = ipaddress.ip_address(address[4][0])
                if not ip.is_global:
                    return "I blocked that private or local network address."
        except (OSError, ValueError) as exc:
            return f"I couldn't resolve that website: {exc}"
        return None

    @staticmethod
    def _fetch_url(url: str) -> ToolResult:
        max_bytes = 2 * 1024 * 1024
        try:
            current = url
            for _ in range(5):
                blocked = TaskAgent._validate_public_url(current)
                if blocked:
                    return ToolResult(False, blocked)
                resp = requests.get(
                    current,
                    timeout=15,
                    headers={"User-Agent": "Mozilla/5.0 (FRIDAY)"},
                    stream=True,
                    allow_redirects=False,
                )
                if 300 <= resp.status_code < 400 and resp.headers.get("location"):
                    from urllib.parse import urljoin

                    current = urljoin(current, resp.headers["location"])
                    resp.close()
                    continue
                resp.raise_for_status()
                break
            else:
                return ToolResult(False, "That page redirected too many times.")
            content_type = resp.headers.get("content-type", "").lower()
            if content_type and not any(kind in content_type for kind in ("text/", "json", "xml")):
                return ToolResult(False, f"Unsupported page content type: {content_type.split(';')[0]}")
            body = bytearray()
            for chunk in resp.iter_content(65536):
                body.extend(chunk)
                if len(body) > max_bytes:
                    return ToolResult(False, "That page is larger than the 2 MB fetch limit.")
            encoding = resp.encoding or "utf-8"
            raw_text = bytes(body).decode(encoding, errors="replace")
        except Exception as exc:
            return ToolResult(False, f"I couldn't fetch that page: {exc}")
        finally:
            if "resp" in locals():
                resp.close()
        text = _html_to_text(raw_text)
        if not text:
            return ToolResult(False, "I couldn't read any text from that page, Boss.")
        limited = text[:9000]
        return ToolResult(
            True,
            f"Content from {url}:\n{limited}"
            + ("\n... (truncated)" if len(text) > 9000 else ""),
            data={"url": current, "text": limited, "truncated": len(text) > len(limited)},
        )
