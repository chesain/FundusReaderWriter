#!/usr/bin/env python3
"""
Simple launcher script for the DICOM Reader/Writer Application
"""
from __future__ import annotations
import sys
import os
from pathlib import Path

# Ensure the repo root is on sys.path
REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT))

# Set Qt plugin path for macOS so PyQt6 can find its plugins even outside conda
if sys.platform == "darwin":
    try:
        import PyQt6
        qt_dir = Path(PyQt6.__file__).parent / "Qt6"
        plugin_dir = qt_dir / "plugins"
        if plugin_dir.exists():
            os.environ.setdefault("QT_PLUGIN_PATH", str(plugin_dir))
    except Exception:
        pass

from PyQt6.QtWidgets import QApplication
from app.ui.main_window import MainWindow
from app.core.dicom_io import initialize_dicom_environment
import logging

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

def main():
    # Initialize DICOM environment first (handlers/config warm-up)
    try:
        initialize_dicom_environment()
    except Exception:
        pass

    # Qt requires QApplication before any widget is created
    app = QApplication(sys.argv)
    app.setApplicationName("DICOM Reader/Writer")
    app.setOrganizationName("CV")

    win = MainWindow()
    win.show()

    # Optional: load a directory passed on the command line
    if len(sys.argv) > 1:
        directory = Path(sys.argv[1])
        if directory.exists() and directory.is_dir():
            win._load_directory(directory)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
