"""Driver listing, problem devices, and driver-update search.

Note: on Windows, drivers are updated through Windows Update or vendor tools.
This module uses the official Windows Update Agent (COM) to *search* for driver
updates; installation is delegated to Windows Update for safety. No third-party
database is used.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import utils


@dataclass
class Device:
    name: str
    status: str
    cls: str
    problem: str = ""


@dataclass
class DriverPackage:
    published_name: str
    provider: str
    cls: str
    version: str
    date: str


@dataclass
class DriverUpdate:
    title: str
    driver_class: str = ""
    version: str = ""


def list_problem_devices() -> list[Device]:
    """Present devices that are not working (the "yellow bang" ones).

    Filters on Status = 'Error' among present devices only: the 'Unknown'
    status marks phantom devices that are not connected, not real problems.
    """
    res = utils.run_powershell(
        "Get-PnpDevice -PresentOnly | "
        "Where-Object { $_.Status -eq 'Error' } | "
        "Select-Object FriendlyName,Status,Class,InstanceId | "
        "ConvertTo-Json -Compress",
        timeout=90,
    )
    return _parse_devices(res.out)


def _parse_devices(text: str) -> list[Device]:
    import json

    text = (text or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    devices = []
    for d in data:
        devices.append(
            Device(
                name=d.get("FriendlyName") or "(unknown)",
                status=str(d.get("Status") or ""),
                cls=str(d.get("Class") or ""),
                problem=str(d.get("Problem") or d.get("InstanceId") or ""),
            )
        )
    return devices


def list_third_party_drivers() -> list[DriverPackage]:
    """Installed third-party driver packages (pnputil)."""
    res = utils.run(["pnputil", "/enum-drivers"], timeout=90)
    return _parse_pnputil(res.out)


def _parse_pnputil(text: str) -> list[DriverPackage]:
    packages: list[DriverPackage] = []
    cur: dict[str, str] = {}

    def flush():
        if cur.get("published_name"):
            packages.append(
                DriverPackage(
                    published_name=cur.get("published_name", ""),
                    provider=cur.get("provider", ""),
                    cls=cur.get("class", ""),
                    version=cur.get("version", ""),
                    date=cur.get("date", ""),
                )
            )

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        # Labels are localized: detect fields by keyword.
        if low.startswith(("published name", "nome pubblicato")):
            flush()
            cur = {"published_name": _value(line)}
        elif "provider" in low and ":" in line:
            cur["provider"] = _value(line)
        elif ("class name" in low or "classe" in low or
              low.startswith("class")) and ":" in line:
            cur.setdefault("class", _value(line))
        elif ("driver version" in low or "versione driver" in low or
              "versione" in low) and ":" in line:
            val = _value(line)
            parts = val.split()
            if len(parts) >= 2:
                cur["date"] = parts[0]
                cur["version"] = parts[-1]
            else:
                cur["version"] = val
    flush()
    return packages


def _value(line: str) -> str:
    return line.split(":", 1)[1].strip() if ":" in line else ""


def search_driver_updates() -> tuple[list[DriverUpdate], str]:
    """Search for driver updates via the Windows Update Agent (COM).

    Returns (updates, error_message).
    """
    script = r"""
try {
  $session = New-Object -ComObject Microsoft.Update.Session
  $searcher = $session.CreateUpdateSearcher()
  $result = $searcher.Search("IsInstalled=0 and Type='Driver'")
  $items = @()
  foreach ($u in $result.Updates) {
    $items += [pscustomobject]@{ Title = $u.Title }
  }
  $items | ConvertTo-Json -Compress
} catch {
  Write-Output ("ERROR:" + $_.Exception.Message)
}
"""
    res = utils.run_powershell(script, timeout=180)
    out = (res.out or "").strip()
    if out.startswith("ERROR:"):
        return [], out[len("ERROR:"):].strip()
    if not out:
        return [], ""
    import json

    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return [], "Invalid response from Windows Update."
    if isinstance(data, dict):
        data = [data]
    return [DriverUpdate(title=d.get("Title", "")) for d in data], ""


def scan_hardware_changes() -> utils.CmdResult:
    """Trigger a scan for new hardware (pnputil /scan-devices)."""
    return utils.run(["pnputil", "/scan-devices"], timeout=120)


def open_windows_update() -> None:
    """Open the Windows Update settings page."""
    utils.run("start ms-settings:windowsupdate")
