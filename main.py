"""SWManager entry point — software manager for Windows.

Run with:  python main.py
"""
import sys

from swmanager.gui import main

if __name__ == "__main__":
    if sys.platform != "win32":
        print("SWManager is designed for Windows.")
        sys.exit(1)
    main()
