#!/usr/bin/env python3
"""
Main entry point for DICOM Reader/Writer Application
"""
import sys
import os
import logging
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from app.ui.main_window import MainWindow
from app.core.dicom_io import initialize_dicom_environment

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

    # Create Qt application
    app = QApplication(sys.argv)
    
    # Set application metadata
    app.setApplicationName("DICOM Reader/Writer")
    app.setOrganizationName("VUWindsurf")
    app.setOrganizationDomain("vuwindsurf.com")
    
    # Enable high DPI scaling
    app.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    # Create and show main window
    window = MainWindow()
    window.show()
    
    # If command line argument provided, load that directory
    if len(sys.argv) > 1:
        directory = Path(sys.argv[1])
        if directory.exists() and directory.is_dir():
            window._load_directory(directory)
    
    # Run application
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
