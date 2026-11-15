"""Cleanup of temporary files and system caches."""
from __future__ import annotations

import glob
import os
import shutil
from dataclasses import dataclass, field

from . import utils


@dataclass
class CleanTarget:
    key: str
    label: str
    paths: list[str] = field(default_factory=list)
    needs_admin: bool = False
    special: str = ""           # 'recyclebin' = handled separately
    contents_only: bool = True  # empty the folder without removing it
    size: int = 0


def _expand(path: str) -> str:
    return os.path.expandvars(path)


def _targets() -> list[CleanTarget]:
    local = os.environ.get("LOCALAPPDATA", "")
    windir = os.environ.get("SystemRoot", r"C:\Windows")
    return [
        CleanTarget(
            "user_temp", "User temp files (%TEMP%)",
            [_expand("%TEMP%")],
        ),
        CleanTarget(
            "win_temp", "Windows temp files",
            [os.path.join(windir, "Temp")],
            needs_admin=True,
        ),
        CleanTarget(
            "prefetch", "Prefetch cache",
            [os.path.join(windir, "Prefetch")],
            needs_admin=True,
        ),
        CleanTarget(
            "win_update", "Windows Update cache (downloads)",
            [os.path.join(windir, "SoftwareDistribution", "Download")],
            needs_admin=True,
        ),
        CleanTarget(
            "thumbnails", "Explorer thumbnail cache",
            [os.path.join(local, "Microsoft", "Windows", "Explorer")]
            if local else [],
        ),
        CleanTarget(
            "edge_cache", "Microsoft Edge cache",
            [os.path.join(local, "Microsoft", "Edge", "User Data",
                          "Default", "Cache")] if local else [],
        ),
        CleanTarget(
            "chrome_cache", "Google Chrome cache",
            [os.path.join(local, "Google", "Chrome", "User Data",
                          "Default", "Cache")] if local else [],
        ),
        CleanTarget(
            "recycle_bin", "Recycle Bin", [], special="recyclebin",
        ),
    ]


def scan() -> list[CleanTarget]:
    """Compute the recoverable size for each category."""
    targets = _targets()
    for t in targets:
        if t.special == "recyclebin":
            t.size = _recyclebin_size()
            continue
        if t.key == "thumbnails":
            t.size = _thumbnail_size(t.paths)
            continue
        t.size = sum(utils.dir_size(p) for p in t.paths if os.path.isdir(p))
    return targets


def _thumbnail_size(paths: list[str]) -> int:
    total = 0
    for base in paths:
        for pattern in ("thumbcache_*.db", "iconcache_*.db"):
            for f in glob.glob(os.path.join(base, pattern)):
                try:
                    total += os.path.getsize(f)
                except OSError:
                    pass
    return total


def _recyclebin_size() -> int:
    res = utils.run_powershell(
        "$s=(New-Object -ComObject Shell.Application).NameSpace(10);"
        "$b=0; if($s){foreach($i in $s.Items()){$b+=$i.Size}}; Write-Output $b",
        timeout=60,
    )
    try:
        return int((res.out or "0").strip() or "0")
    except ValueError:
        return 0


def _empty_dir(path: str) -> tuple[int, int]:
    """Empty a folder. Returns (bytes_freed, errors)."""
    freed = 0
    errors = 0
    if not os.path.isdir(path):
        return 0, 0
    for entry in os.scandir(path):
        try:
            if entry.is_file() or entry.is_symlink():
                size = entry.stat(follow_symlinks=False).st_size
                os.remove(entry.path)
                freed += size
            elif entry.is_dir():
                size = utils.dir_size(entry.path)
                shutil.rmtree(entry.path, ignore_errors=True)
                if not os.path.isdir(entry.path):
                    freed += size
                else:
                    errors += 1
        except (OSError, PermissionError):
            errors += 1
    return freed, errors


def _clean_thumbnails(paths: list[str]) -> tuple[int, int]:
    freed, errors = 0, 0
    for base in paths:
        for pattern in ("thumbcache_*.db", "iconcache_*.db"):
            for f in glob.glob(os.path.join(base, pattern)):
                try:
                    size = os.path.getsize(f)
                    os.remove(f)
                    freed += size
                except OSError:
                    errors += 1
    return freed, errors


def clean_target(t: CleanTarget) -> tuple[int, int]:
    """Clean one category. Returns (bytes_freed, errors)."""
    if t.special == "recyclebin":
        res = utils.run_powershell(
            "Clear-RecycleBin -Force -ErrorAction SilentlyContinue", timeout=120
        )
        return (t.size if res.ok else 0), (0 if res.ok else 1)

    if t.key == "thumbnails":
        return _clean_thumbnails(t.paths)

    freed, errors = 0, 0
    for p in t.paths:
        f, e = _empty_dir(p)
        freed += f
        errors += e
    return freed, errors
