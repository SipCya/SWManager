"""SWManager - software manager for Windows.

Modules:
    utils     - command execution, privileges, formatting
    programs  - program management via winget (list/update/uninstall/recovery)
    cleanup   - temporary files and cache cleanup
    drivers   - driver listing and update checks
    leftovers - leftovers from uninstalled programs
    icons     - program icon extraction
    gui       - CustomTkinter interface
"""

__version__ = "1.0.0"
__all__ = ["utils", "programs", "cleanup", "drivers", "leftovers", "icons",
           "gui"]
