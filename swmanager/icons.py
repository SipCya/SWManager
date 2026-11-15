"""Extraction of installed program icons (from the Windows registry).

Icons are extracted from the real executables via System.Drawing and cached as
PNG files, so they can be shown next to each program in the list.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile

from . import utils

CACHE_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", tempfile.gettempdir()), "SWManager", "icons")

_registry_index: list[dict] | None = None


def _ensure_cache() -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)


def _normalize(name: str) -> str:
    name = name.lower()
    name = re.sub(r"\(.*?\)", " ", name)            # drop (x64 en-US) etc.
    name = re.sub(r"[0-9]+(\.[0-9]+)+", " ", name)   # drop versions
    name = re.sub(r"[^a-z0-9]+", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def _load_registry_index() -> list[dict]:
    """Read the uninstall keys: DisplayName + DisplayIcon."""
    global _registry_index
    if _registry_index is not None:
        return _registry_index

    script = r"""
$paths = @(
  'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
  'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
  'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
$out = @()
foreach ($p in $paths) {
  Get-ItemProperty $p -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.DisplayName) {
      $out += [pscustomobject]@{
        name = $_.DisplayName
        icon = $_.DisplayIcon
        loc  = $_.InstallLocation
      }
    }
  }
}
$out | ConvertTo-Json -Compress
"""
    res = utils.run_powershell(script, timeout=90)
    try:
        data = json.loads((res.out or "").strip() or "[]")
    except json.JSONDecodeError:
        data = []
    if isinstance(data, dict):
        data = [data]
    _registry_index = [d for d in data if d.get("name")]
    return _registry_index


def _best_source(name: str, index: list[dict]) -> str | None:
    """Find the most plausible icon source for a program name."""
    target = _normalize(name)
    if not target:
        return None
    best = None
    for entry in index:
        reg = _normalize(entry.get("name", ""))
        if not reg:
            continue
        if reg == target:
            score = 3
        elif target in reg or reg in target:
            score = 2
        else:
            continue
        src = entry.get("icon") or ""
        if not src and entry.get("loc"):
            src = entry["loc"]
        if not src:
            continue
        if best is None or score > best[0]:
            best = (score, src)
            if score == 3:
                break
    return best[1] if best else None


def _cache_path(name: str) -> str:
    h = hashlib.md5(name.encode("utf-8", "ignore")).hexdigest()[:16]
    return os.path.join(CACHE_DIR, f"{h}.png")


def extract_icons(names: list[str]) -> dict[str, str]:
    """Return {name: png_path} for the names an icon can be found for.

    Cached icons are not re-extracted. New files are extracted in a single
    PowerShell process.
    """
    _ensure_cache()
    index = _load_registry_index()

    result: dict[str, str] = {}
    jobs = []
    for name in names:
        cache = _cache_path(name)
        if os.path.exists(cache):
            if os.path.getsize(cache) > 0:
                result[name] = cache
            continue
        src = _best_source(name, index)
        if src:
            jobs.append({"name": name, "src": src, "out": cache})

    if not jobs:
        return result

    job_file = os.path.join(CACHE_DIR, "_job.json")
    with open(job_file, "w", encoding="utf-8") as fh:
        json.dump(jobs, fh)

    script = (
        "Add-Type -AssemblyName System.Drawing; "
        f"$jobs = Get-Content -Raw -LiteralPath '{job_file}' | "
        "ConvertFrom-Json; "
        "foreach ($j in $jobs) { try { "
        "  $src = $j.src -replace '\"',''; "
        "  if ($src -match '^(.*\\.(exe|dll|ico))\\s*,\\s*-?\\d+$') "
        "{ $src = $Matches[1] } "
        "  if (-not (Test-Path -LiteralPath $src)) { continue } "
        "  if ($src.ToLower().EndsWith('.ico')) "
        "{ $ic = New-Object System.Drawing.Icon($src) } "
        "  else { $ic = [System.Drawing.Icon]::ExtractAssociatedIcon($src) } "
        "  if ($ic) { $bmp = $ic.ToBitmap(); "
        "    $bmp.Save($j.out, [System.Drawing.Imaging.ImageFormat]::Png); "
        "    $bmp.Dispose(); $ic.Dispose() } "
        "} catch {} }"
    )
    utils.run_powershell(script, timeout=180)

    for j in jobs:
        if os.path.exists(j["out"]) and os.path.getsize(j["out"]) > 0:
            result[j["name"]] = j["out"]
    try:
        os.remove(job_file)
    except OSError:
        pass
    return result
