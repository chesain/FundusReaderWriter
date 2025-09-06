#!/usr/bin/env python3
"""
Simple launcher script for the DICOM Reader/Writer Application
"""
import sys
import os
from pathlib import Path

# Set Qt plugin path for macOS
if sys.platform == "darwin":
    import PyQt6
    qt_dir = Path(PyQt6.__file__).parent / "Qt6"
    plugin_dir = qt_dir / "plugins"
    if plugin_dir.exists():
        os.environ['QT_PLUGIN_PATH'] = str(plugin_dir)

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Import and run the application
from app.ui.main_window import MainWindow
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from app.core.dicom_io import initialize_dicom_environment
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def main():
    """Main application entry point"""
    # Initialize DICOM environment (handlers/config warm-up)
    try:
        initialize_dicom_environment()
    except Exception:
        pass

    app = QApplication(sys.argv)
    
    # Set application metadata
    app.setApplicationName("DICOM Reader/Writer")
    app.setOrganizationName("VUWindsurf")
    
    # Create and show main window
    window = MainWindow()
    window.show()
    
    # If command line argument provided, load that directory
    if len(sys.argv) > 1:
        directory = Path(sys.argv[1])
        if directory.exists() and directory.is_dir():
            window._load_directory(directory)
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
