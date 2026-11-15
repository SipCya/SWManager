"""Detection of leftovers from uninstalled programs.

Two kinds of leftovers:
  * broken shortcuts (.lnk whose target no longer exists) -> reliable
  * leftover folders in AppData/ProgramData/Program Files not matching any
    installed program -> heuristic, needs manual review

All deletions go to the **Recycle Bin** (recoverable), never permanent.
"""
from __future__ import annotations

import json
import os
import stat as _stat
import tempfile
from dataclasses import dataclass

from . import icons, utils


@dataclass
class BrokenShortcut:
    path: str
    name: str
    target: str


@dataclass
class LeftoverFolder:
    path: str
    name: str
    category: str
    size: int
    approx: bool = False


# --------------------------------------------------------- broken shortcuts
def scan_broken_shortcuts() -> list[BrokenShortcut]:
    script = r"""
$sh = New-Object -ComObject WScript.Shell
$dirs = @(
  [Environment]::GetFolderPath('Desktop'),
  [Environment]::GetFolderPath('CommonDesktopDirectory'),
  [Environment]::GetFolderPath('StartMenu'),
  [Environment]::GetFolderPath('CommonStartMenu'),
  (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu'),
  (Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu')
) | Select-Object -Unique
$res = @()
foreach ($d in $dirs) {
  if (-not (Test-Path -LiteralPath $d)) { continue }
  Get-ChildItem -LiteralPath $d -Recurse -Filter *.lnk -ErrorAction SilentlyContinue |
  ForEach-Object {
    try {
      $lnk = $sh.CreateShortcut($_.FullName)
      $t = $lnk.TargetPath
      if ($t -and ($t -match '^[A-Za-z]:\\') -and
          -not (Test-Path -LiteralPath $t)) {
        $res += [pscustomobject]@{ path=$_.FullName; name=$_.BaseName; target=$t }
      }
    } catch {}
  }
}
$res | ConvertTo-Json -Compress
"""
    res = utils.run_powershell(script, timeout=120)
    data = _json_list(res.out)
    return [BrokenShortcut(path=d.get("path", ""), name=d.get("name", ""),
                           target=d.get("target", "")) for d in data
            if d.get("path")]


# ----------------------------------------------------------- leftover folders
_SAFE_NAMES = {
    "microsoft", "windows", "windowsapps", "common files", "package cache",
    "packages", "temp", "tmp", "cache", "microsoft shared", "windows defender",
    "windowspowershell", "powershell", "dotnet", "microsoft.net", "assembly",
    "nvidia", "nvidia corporation", "intel", "amd", "realtek", "google",
    "mozilla", "mozilla firefox", "internet explorer", "microsoft onedrive",
    "onedrive", "application data", "microsoft office", "office", "edge",
    "microsoftedge", "comms", "connecteddevicesplatform", "virtualstore",
    "grouppolicy", "diagnostics", "elevateddiagnostics", "d3dscache",
    "crashdumps", "publishing", "vmware", "oracle", "java", "common",
    "microsoft visual studio", "microsoftvisualstudio", "winget",
    "swmanager", "programs", "lenovo", "hp", "dell", "asus", "logishrd",
    "logitech",
}


def _skip_entry(entry: os.DirEntry) -> bool:
    """Skip reparse points (junction/symlink) and hidden+system folders.

    Protects Windows compatibility junctions (e.g. "Application Data",
    "Dati applicazioni", "History") that Python does not report as symlinks.
    """
    try:
        st = entry.stat(follow_symlinks=False)
    except OSError:
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    if attrs & _stat.FILE_ATTRIBUTE_REPARSE_POINT:
        return True
    if (attrs & _stat.FILE_ATTRIBUTE_HIDDEN) and \
            (attrs & _stat.FILE_ATTRIBUTE_SYSTEM):
        return True
    return False


def _capped_size(path: str, max_files: int = 12000) -> tuple[int, bool]:
    """Folder size, stopping after max_files files.

    Returns (bytes, approximate). Avoids fully walking huge folders just to
    display their size.
    """
    total = 0
    count = 0
    for root, _dirs, files in os.walk(path, onerror=lambda e: None):
        for name in files:
            try:
                fp = os.path.join(root, name)
                if not os.path.islink(fp):
                    total += os.path.getsize(fp)
            except OSError:
                continue
            count += 1
            if count >= max_files:
                return total, True
    return total, False


def _norm_tokens(name: str) -> set[str]:
    out = set()
    cur = ""
    for ch in name.lower():
        if ch.isalnum():
            cur += ch
        else:
            if len(cur) >= 4:
                out.add(cur)
            cur = ""
    if len(cur) >= 4:
        out.add(cur)
    return out


def _is_safe(name: str) -> bool:
    low = name.lower()
    if low in _SAFE_NAMES:
        return True
    if low.startswith((".", "microsoft", "windows", "nvidia", "intel")):
        return True
    return False


def _installed_signatures() -> set[str]:
    sigs: set[str] = set()
    for entry in icons._load_registry_index():
        sigs |= _norm_tokens(entry.get("name", ""))
        loc = entry.get("loc") or ""
        if loc:
            sigs |= _norm_tokens(os.path.basename(loc.rstrip("\\/")))
    return sigs


def _candidate_dirs() -> list[tuple[str, str]]:
    env = os.environ.get
    pairs = [
        (env("LOCALAPPDATA", ""), "AppData\\Local"),
        (env("APPDATA", ""), "AppData\\Roaming"),
        (env("ProgramData", r"C:\ProgramData"), "ProgramData"),
        (env("ProgramFiles", r"C:\Program Files"), "Program Files"),
        (env("ProgramFiles(x86)", ""), "Program Files (x86)"),
    ]
    return [(p, label) for p, label in pairs if p and os.path.isdir(p)]


def scan_leftover_folders(max_items: int = 120) -> list[LeftoverFolder]:
    sigs = _installed_signatures()
    found: list[LeftoverFolder] = []
    for base, label in _candidate_dirs():
        try:
            entries = list(os.scandir(base))
        except OSError:
            continue
        for e in entries:
            if not e.is_dir() or e.is_symlink() or _skip_entry(e):
                continue
            name = e.name
            if _is_safe(name):
                continue
            tokens = _norm_tokens(name)
            if not tokens or tokens & sigs:
                continue  # matches an installed program
            size, approx = _capped_size(e.path)
            found.append(LeftoverFolder(path=e.path, name=name,
                                        category=label, size=size,
                                        approx=approx))
            if len(found) >= max_items:
                break
        if len(found) >= max_items:
            break
    found.sort(key=lambda f: f.size, reverse=True)
    return found


# ------------------------------------------------------------- empty folders
def _has_file(path: str) -> bool:
    """True if any file exists anywhere in the subtree."""
    for _root, _dirs, files in os.walk(path, onerror=lambda e: None):
        if files:
            return True
    return False


def scan_empty_folders(max_items: int = 200) -> list[LeftoverFolder]:
    """Completely empty leftover folders (no files, only subfolders).

    Very safe to remove: they contain no data.
    """
    found: list[LeftoverFolder] = []
    for base, label in _candidate_dirs():
        try:
            entries = list(os.scandir(base))
        except OSError:
            continue
        for e in entries:
            if not e.is_dir() or e.is_symlink() or _skip_entry(e):
                continue
            if _is_safe(e.name):
                continue
            try:
                if not _has_file(e.path):
                    found.append(LeftoverFolder(path=e.path, name=e.name,
                                                category=label, size=0))
            except OSError:
                continue
            if len(found) >= max_items:
                return found
    return found


# ------------------------------------------------------ delete to Recycle Bin
def delete_to_recycle_bin(paths: list[str]) -> tuple[int, int]:
    """Move paths to the Recycle Bin. Returns (deleted, errors)."""
    paths = [p for p in paths if p]
    if not paths:
        return 0, 0
    icons._ensure_cache()
    job = os.path.join(icons.CACHE_DIR, "_deljob.json")
    with open(job, "w", encoding="utf-8") as fh:
        json.dump(paths, fh)

    script = (
        "Add-Type -AssemblyName Microsoft.VisualBasic; "
        f"$items = Get-Content -Raw -LiteralPath '{job}' | ConvertFrom-Json; "
        "$ok=0; $err=0; "
        "foreach ($p in $items) { try { "
        "  if (-not (Test-Path -LiteralPath $p)) { continue } "
        "  $it = Get-Item -LiteralPath $p -Force; "
        "  if ($it.PSIsContainer) { "
        "    [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory($p, "
        "      [Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs, "
        "      [Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin) "
        "  } else { "
        "    [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($p, "
        "      [Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs, "
        "      [Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin) "
        "  } $ok++ "
        "} catch { $err++ } } "
        "Write-Output (\"$ok/$err\")"
    )
    res = utils.run_powershell(script, timeout=300)
    try:
        os.remove(job)
    except OSError:
        pass
    out = (res.out or "").strip().splitlines()
    for line in reversed(out):
        if "/" in line:
            a, _, b = line.partition("/")
            try:
                return int(a), int(b)
            except ValueError:
                break
    return 0, len(paths)


def _json_list(text: str) -> list[dict]:
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
