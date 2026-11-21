"""Shared utilities: command execution, privileges, formatting."""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from dataclasses import dataclass

# Prevents a black console window from flashing on every command.
_CREATE_NO_WINDOW = 0x08000000


def _hidden_startupinfo():
    """STARTUPINFO forcing SW_HIDE: no flashing console window."""
    if not hasattr(subprocess, "STARTUPINFO"):
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    return si


@dataclass
class CmdResult:
    code: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.code == 0


def run(args, timeout: int | None = 180, cwd: str | None = None) -> CmdResult:
    """Run a command without opening any console window.

    `args` may be a list (preferred) or a string (shell). Output is decoded as
    UTF-8 with character replacement, since winget uses UTF-8 for its table art.
    """
    shell = isinstance(args, str)
    try:
        proc = subprocess.run(
            args,
            shell=shell,
            capture_output=True,
            timeout=timeout,
            cwd=cwd,
            creationflags=_CREATE_NO_WINDOW,
            startupinfo=_hidden_startupinfo(),
        )
    except subprocess.TimeoutExpired:
        return CmdResult(124, "", f"Timed out after {timeout}s")
    except FileNotFoundError as exc:
        return CmdResult(127, "", str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        return CmdResult(1, "", str(exc))

    out = (proc.stdout or b"").decode("utf-8", errors="replace")
    err = (proc.stderr or b"").decode("utf-8", errors="replace")
    return CmdResult(proc.returncode, out, err)


def run_powershell(script: str, timeout: int | None = 180) -> CmdResult:
    """Run a PowerShell script forcing UTF-8 output."""
    full = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
        "$ProgressPreference='SilentlyContinue'; " + script
    )
    return run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            full,
        ],
        timeout=timeout,
    )


def is_admin() -> bool:
    """True if the process has administrator privileges."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """Relaunch the application elevated (UAC).

    Returns True if the elevation request was issued (the current process
    should then exit), False on error.
    """
    try:
        script = os.path.abspath(sys.argv[0])
        workdir = os.path.dirname(script)
        args = [script] + sys.argv[1:]
        params = " ".join(f'"{a}"' for a in args)
        # An elevated process starts in system32 by default, so pass an
        # absolute script path and the working directory explicitly.
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, workdir, 1
        )
        return int(rc) > 32  # ShellExecuteW returns > 32 on success.
    except Exception:
        return False


def human_size(num_bytes: int) -> str:
    """Format a byte size in a human-readable way."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def dir_size(path: str) -> int:
    """Total size (bytes) of a folder, ignoring access errors."""
    total = 0
    if not path or not os.path.isdir(path):
        return 0
    for root, _dirs, files in os.walk(path, onerror=lambda e: None):
        for name in files:
            try:
                fp = os.path.join(root, name)
                if not os.path.islink(fp):
                    total += os.path.getsize(fp)
            except OSError:
                continue
    return total
