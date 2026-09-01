import pathlib
import re

root = pathlib.Path.cwd()
base = str(root / "py312")
venv = str(root / ".venv")
newroot = str(root)


def fix_text(text):
    text = re.sub(
        r"[A-Za-z]:[\\/][^\"';\r\n]*?[\\/]friday-kit(?=[\\/])",
        lambda m: newroot,
        text,
    )
    text = re.sub(r"(?im)^home\s*=.*$", lambda m: "home = " + base, text)
    text = re.sub(r"(?im)^executable\s*=.*$", lambda m: "executable = " + str(pathlib.Path(base) / "python.exe"), text)
    text = re.sub(r"(?im)^command\s*=.*$", lambda m: "command = " + str(pathlib.Path(base) / "python.exe") + " -m venv " + venv, text)
    text = re.sub(r"(?im)(^set\s+\"VIRTUAL_ENV=).*$", lambda m: 'set "VIRTUAL_ENV=' + venv + '"', text)
    text = re.sub(r"(?im)(VIRTUAL_ENV=\$\(cygpath ')[^']*('\))", lambda m: m.group(1) + venv + m.group(2), text)
    text = re.sub(r"(?im)(export VIRTUAL_ENV=')[^']*(')", lambda m: m.group(1) + venv + m.group(2), text)
    return text


for rel in [".venv/pyvenv.cfg", ".venv/Scripts/activate.bat", ".venv/Scripts/activate"]:
    p = pathlib.Path(rel)
    if p.exists():
        p.write_text(fix_text(p.read_text(encoding="utf-8", errors="ignore")), encoding="utf-8")

for exe in pathlib.Path(".venv/Scripts").glob("*.exe"):
    data = exe.read_bytes()
    if b"friday-kit" not in data:
        continue
    match = re.search(rb"[A-Za-z]:[\\/][^\r\n]*?[\\/]friday-kit[\\/]", data)
    if not match:
        continue
    old_root = match.group(0)[:-1]
    new_bytes = newroot.encode()
    if len(old_root) == len(new_bytes):
        exe.write_bytes(data.replace(old_root, new_bytes))
    else:
        print("WARNING: cannot auto-patch launcher", exe.name, "- rebuild the venv to regenerate it.")