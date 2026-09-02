from __future__ import annotations

import base64
import copy
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import requests

from core import config


class CloudProviderError(RuntimeError):
    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


RETRYABLE_HTTP_STATUS = frozenset({401, 402, 403, 408, 429})


class OpenRouterClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._explicit_api_key = api_key is not None
        self.api_key = config.OPENROUTER_API_KEY if api_key is None else api_key.strip()
        self.model = model or config.OPENROUTER_MODEL
        self.base_url = (base_url or config.OPENROUTER_BASE_URL).rstrip("/")
        self.timeout = timeout or config.OPENROUTER_TIMEOUT
        self._runtime_mode: str | None = None
        self.fallback_api_key = config.HERMES_API_KEY
        self.fallback_model = config.HERMES_MODEL
        self.fallback_base_url = config.HERMES_BASE_URL
        self.last_provider: str | None = None

    def set_mode(self, mode: str) -> None:
        """Override the reasoning mode at runtime ('local' or 'openrouter')."""
        self._runtime_mode = mode if mode in {"local", "openrouter"} else None

    @property
    def selected_mode(self) -> str:
        return self._runtime_mode or config.REASONING_MODE

    @property
    def available(self) -> bool:
        return bool(self.api_key or self.fallback_api_key)

    @property
    def fallback_ready(self) -> bool:
        return (
            config.CLOUD_FALLBACK_ENABLED
            and bool(self.fallback_api_key)
            and self.fallback_base_url.rstrip("/") != self.base_url.rstrip("/")
        )

    @property
    def enabled(self) -> bool:
        mode = self.selected_mode
        if self._explicit_api_key:
            return True
        return mode == "openrouter" and bool(self.api_key or self.fallback_api_key)

    @staticmethod
    def _image_data_url(url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme != "file":
            return url
        path = Path(url2pathname(unquote(parsed.path))).resolve()
        if not path.is_file():
            raise CloudProviderError(f"Attached image no longer exists: {path.name}")
        data = path.read_bytes()
        if len(data) > 10 * 1024 * 1024:
            raise CloudProviderError("Attached image exceeds the 10 MB cloud limit.")
        media_type = mimetypes.guess_type(path.name)[0] or "image/png"
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{media_type};base64,{encoded}"

    @classmethod
    def prepare_messages(cls, messages: list[dict]) -> list[dict]:
        prepared = copy.deepcopy(messages)
        for message in prepared:
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if part.get("type") != "image_url":
                    continue
                image = part.get("image_url") or {}
                url = str(image.get("url") or "")
                image["url"] = cls._image_data_url(url)
                part["image_url"] = image
        return prepared

    def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
    ) -> dict:
        if not self.enabled:
            raise CloudProviderError("Cloud reasoning is not configured.")
        attempts = []
        if self.api_key:
            attempts.append(
                ("OpenRouter", self.base_url, self.api_key, self.model)
            )
        if self.fallback_ready:
            attempts.append(
                (
                    "Hermes Portal",
                    self.fallback_base_url,
                    self.fallback_api_key,
                    self.fallback_model,
                )
            )
        errors: list[CloudProviderError] = []
        for label, base_url, api_key, model in attempts:
            try:
                return self._request(
                    label, base_url, api_key, model, messages, tools, tool_choice
                )
            except CloudProviderError as exc:
                errors.append(exc)
                if not exc.retryable:
                    raise
        if not errors:
            raise CloudProviderError("Cloud reasoning is not configured.")
        if len(errors) > 1:
            raise CloudProviderError(
                f"{errors[0]}; {errors[-1]}", retryable=errors[0].retryable
            )
        raise errors[0]

    def _request(
        self,
        label: str,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[dict],
        tools: list[dict] | None,
        tool_choice: str,
    ) -> dict:
        payload: dict = {
            "model": model,
            "messages": self.prepare_messages(messages),
            "temperature": config.GEN_TEMPERATURE,
            "top_p": config.GEN_TOP_P,
            "max_tokens": config.OPENROUTER_MAX_TOKENS,
        }
        if config.OPENROUTER_REASONING_ENABLED:
            payload["reasoning"] = {"enabled": True}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if label == "OpenRouter":
            headers["HTTP-Referer"] = "http://localhost/friday-kit"
            headers["X-OpenRouter-Title"] = "FRIDAY Local Agent"
        try:
            response = requests.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise CloudProviderError(
                f"{label} connection failed: {exc.__class__.__name__}",
                retryable=True,
            ) from exc
        if response.status_code >= 400:
            retryable = (
                response.status_code in RETRYABLE_HTTP_STATUS
                or response.status_code >= 500
            )
            message = f"{label} returned HTTP {response.status_code}"
            try:
                detail = response.json().get("error", {}).get("message")
                if detail:
                    safe_detail = str(detail)
                    for secret in (api_key, self.api_key):
                        if secret:
                            safe_detail = safe_detail.replace(secret, "[redacted]")
                    message += f": {safe_detail[:300]}"
            except (ValueError, AttributeError):
                pass
            raise CloudProviderError(message, retryable=retryable)
        try:
            payload = response.json()
            choice = payload["choices"][0]
            message = choice["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise CloudProviderError(
                f"{label} returned an invalid completion response."
            ) from exc
        self.last_provider = label
        return {
            "message": message,
            "finish_reason": choice.get("finish_reason"),
            "model": payload.get("model", model),
            "usage": payload.get("usage") or {},
            "provider": label,
        }
