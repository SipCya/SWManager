"""Program management via winget: list, upgrades, uninstall, and recovery.

Recovery helpers handle the common cases where ``winget uninstall`` fails:
multiple installed versions, and "ghost" entries that still show up in the
list even though the application is already gone (orphaned registry entries or
leftover MSIX/Appx packages).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import utils


@dataclass
class Program:
    name: str
    pkg_id: str
    version: str
    available: str = ""   # available version (upgrades only)
    source: str = ""

    @property
    def upgradable(self) -> bool:
        return bool(self.available)


@dataclass
class ArpEntry:
    display: str
    pspath: str          # PowerShell registry path (for removal)
    uninstall: str
    location: str


@dataclass
class AppxPackage:
    name: str
    full_name: str


_COMMON = ["--disable-interactivity", "--accept-source-agreements"]


def winget_available() -> bool:
    return utils.run(["winget", "--version"], timeout=20).ok


# ------------------------------------------------------------- table parsing
def _find_header(lines: list[str]) -> int:
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("Name") and "Id" in line and "Version" in line:
            return i
    return -1


def _columns(header: str) -> list[tuple[str, int]]:
    """Return [(column_name, start_index), ...] sorted by position.

    winget left-aligns each value under the start of its column title, so the
    title position in the header marks the column start.
    """
    cols = []
    for title in ("Name", "Id", "Version", "Available", "Source"):
        idx = header.find(title)
        if idx != -1:
            cols.append((title.lower(), idx))
    cols.sort(key=lambda c: c[1])
    return cols


def _parse_table(text: str) -> list[Program]:
    lines = text.splitlines()
    hi = _find_header(lines)
    if hi == -1:
        return []
    cols = _columns(lines[hi])
    if not cols:
        return []

    programs: list[Program] = []
    for raw in lines[hi + 1:]:
        if not raw.strip():
            continue
        # Skip the dashes separator and any summary/progress lines.
        if set(raw.strip()) <= set("-─ "):
            continue
        if raw.lstrip().startswith(("\\", "|", "/", "-")) and "  " not in raw:
            continue

        values = {}
        for j, (name, start) in enumerate(cols):
            end = cols[j + 1][1] if j + 1 < len(cols) else len(raw)
            values[name] = raw[start:end].strip()

        name = values.get("name", "")
        pkg_id = values.get("id", "")
        if not name or not pkg_id:
            continue
        if " " in pkg_id and not values.get("version"):
            continue
        programs.append(
            Program(
                name=name,
                pkg_id=pkg_id,
                version=values.get("version", ""),
                available=values.get("available", ""),
                source=values.get("source", ""),
            )
        )
    return programs


def list_installed() -> list[Program]:
    """List every program known to winget."""
    res = utils.run(["winget", "list"] + _COMMON, timeout=120)
    return _parse_table(res.out)


def list_upgradable() -> list[Program]:
    """List programs that have an available upgrade."""
    res = utils.run(
        ["winget", "upgrade", "--include-unknown"] + _COMMON, timeout=120
    )
    return [p for p in _parse_table(res.out) if p.available]


# --------------------------------------------------------------- operations
def upgrade(pkg_id: str) -> utils.CmdResult:
    """Upgrade a single package."""
    return utils.run(
        [
            "winget", "upgrade", "--id", pkg_id, "--exact",
            "--silent", "--accept-package-agreements",
            "--accept-source-agreements", "--disable-interactivity",
        ],
        timeout=1200,
    )


def upgrade_all() -> utils.CmdResult:
    """Upgrade every package that has an available upgrade."""
    return utils.run(
        [
            "winget", "upgrade", "--all", "--silent", "--include-unknown",
            "--accept-package-agreements", "--accept-source-agreements",
            "--disable-interactivity",
        ],
        timeout=3600,
    )


def uninstall(pkg_id: str, all_versions: bool = False) -> utils.CmdResult:
    """Uninstall a package by Id. With ``all_versions`` removes every version."""
    args = [
        "winget", "uninstall", "--id", pkg_id, "--exact",
        "--silent", "--disable-interactivity",
    ]
    if all_versions:
        args.append("--all-versions")
    return utils.run(args, timeout=1200)


# ----------------------------------------------------------------- recovery
def classify_error(res: utils.CmdResult) -> str:
    """Classify an uninstall result: ok | multiple | notfound | other."""
    if res.ok:
        return "ok"
    text = ((res.out or "") + (res.err or "")).lower()
    if "multiple versions" in text or "--all-versions" in text:
        return "multiple"
    if ("0x800401f5" in text or "application not found" in text
            or "no installed package found" in text
            or "no suitable package" in text):
        return "notfound"
    return "other"


def keyword(name: str) -> str:
    """A single distinctive search token derived from a program name."""
    name = re.sub(r"version.*$", "", name, flags=re.IGNORECASE)
    tokens = [t for t in re.findall(r"[A-Za-z0-9]+", name)
              if len(t) >= 3 and t.lower() not in {"the", "app", "for"}]
    return tokens[0] if tokens else (name.strip() or name)


def _safe(kw: str) -> str:
    return re.sub(r"[^A-Za-z0-9 ]", "", kw)


def find_appx(kw: str) -> list[AppxPackage]:
    """Find installed MSIX/Appx packages matching a keyword (current user)."""
    kw = _safe(kw)
    if not kw:
        return []
    res = utils.run_powershell(
        f"Get-AppxPackage | Where-Object {{ $_.Name -match '{kw}' }} | "
        "Select-Object Name,PackageFullName | ConvertTo-Json -Compress",
        timeout=90,
    )
    data = _json_list(res.out)
    return [AppxPackage(name=d.get("Name", ""),
                        full_name=d.get("PackageFullName", ""))
            for d in data if d.get("PackageFullName")]


def remove_appx(full_name: str) -> utils.CmdResult:
    """Remove an MSIX/Appx package (no admin needed for per-user packages)."""
    return utils.run_powershell(
        f"Remove-AppxPackage -Package '{full_name}' -ErrorAction Stop",
        timeout=180,
    )


def find_arp(kw: str) -> list[ArpEntry]:
    """Find Add/Remove-Programs registry entries matching a keyword."""
    kw = _safe(kw)
    if not kw:
        return []
    script = (
        "$paths=@("
        "'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',"
        "'HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',"
        "'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*');"
        "$r=@(); foreach($p in $paths){ Get-ItemProperty $p -EA SilentlyContinue |"
        f" Where-Object {{ $_.DisplayName -and ($_.DisplayName -like '*{kw}*') }} |"
        " ForEach-Object { $r += [pscustomobject]@{ display=$_.DisplayName;"
        " pspath=$_.PSPath; uninstall=$_.UninstallString;"
        " loc=$_.InstallLocation } } }; $r | ConvertTo-Json -Compress"
    )
    res = utils.run_powershell(script, timeout=90)
    data = _json_list(res.out)
    return [ArpEntry(display=d.get("display", ""), pspath=d.get("pspath", ""),
                     uninstall=d.get("uninstall") or "",
                     location=d.get("loc") or "")
            for d in data if d.get("pspath")]


def remove_registry_key(pspath: str) -> utils.CmdResult:
    """Delete an orphaned uninstall registry key (may require admin for HKLM)."""
    safe = pspath.replace("'", "''")
    return utils.run_powershell(
        f"Remove-Item -LiteralPath '{safe}' -Recurse -Force -ErrorAction Stop",
        timeout=60,
    )


def _json_list(text: str) -> list[dict]:
    import json

    text = (text or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        return [data]
    return data if isinstance(data, list) else []
