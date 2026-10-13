"""
Creates a Windows desktop shortcut for WhatsApp Transcriber.
Run this once after cloning the repo.

Uses pythonw.exe (no console window) if available, otherwise python.exe.
"""

import sys
import subprocess
from pathlib import Path


def find_pythonw() -> Path:
    exe = Path(sys.executable)
    pythonw = exe.parent / "pythonw.exe"
    return pythonw if pythonw.exists() else exe


def main() -> None:
    here     = Path(__file__).resolve().parent
    script   = here / "transcriber.py"
    icon     = here / "icon.ico"
    pythonw  = find_pythonw()
    desktop  = Path.home() / "Desktop"
    shortcut = desktop / "WhatsApp Transcriber.lnk"

    # Generate icon if it doesn't exist yet
    if not icon.exists():
        print("Generating icon …")
        subprocess.check_call([sys.executable, str(here / "make_icon.py")])

    # PowerShell one-liner via WScript.Shell COM object
    ps = f"""
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut('{shortcut}')
$sc.TargetPath    = '{pythonw}'
$sc.Arguments     = '"{script}"'
$sc.WorkingDirectory = '{here}'
$sc.IconLocation  = '{icon},0'
$sc.Description   = 'WhatsApp Transcriber – transcribe voice messages from WhatsApp exports'
$sc.Save()
"""
    subprocess.check_call(["powershell", "-NoProfile", "-Command", ps])

    print(f"OK  Shortcut created: {shortcut}")
    print(f"   Runs: {pythonw} \"{script}\"")


if __name__ == "__main__":
    main()
