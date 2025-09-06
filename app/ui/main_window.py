"""
Main application window for DICOM Reader/Writer
"""
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                            QSplitter, QMenuBar, QMenu, QToolBar, QStatusBar,
                            QFileDialog, QMessageBox, QProgressDialog, QDockWidget)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from PyQt6.QtGui import QAction, QKeySequence
from pathlib import Path
import logging
from typing import Optional

from app.core.dicom_io import DicomFile
from app.core.regular_image import RegularImageFile
from app.ui.file_browser import FileBrowser
from app.ui.image_viewer import ImageViewer
from app.ui.metadata_panel import MetadataPanel
from app.core.dicom_io import DicomDirectory, DicomFile
from app.core.export import Exporter, ExportConfig

logger = logging.getLogger(__name__)


class WorkerThread(QThread):
    """Worker thread for async operations"""
    progress = pyqtSignal(int, int, str)  # current, total, message
    finished = pyqtSignal(dict)  # results
    error = pyqtSignal(str)
    
    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
    
    def run(self):
        try:
            result = self.func(*self.args, **self.kwargs)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.current_folder: Optional[Path] = None
        self.current_directory: Optional[Path] = None
        self.current_file: Optional[DicomFile] = None
        self.file_list = []
        self.loaded_files = {}
        self.settings = QSettings("VUWindsurf", "DicomReaderWriter")
        self.export_config = ExportConfig()
        self._setup_ui()
        self._setup_actions()
        self._setup_toolbar()
        self._setup_menubar()
        self._restore_settings()
    
    def _setup_ui(self):
        """Setup the main UI layout"""
        self.setWindowTitle("DICOM Fundus Reader/Writer")
        self.setGeometry(100, 100, 1400, 900)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QHBoxLayout(central_widget)
        
        # Create main splitter
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left panel - File browser (dockable)
        self.file_browser_dock = QDockWidget("File Browser", self)
        self.file_browser = FileBrowser()
        self.file_browser.file_selected.connect(self.display_file)
        self.file_browser_dock.setWidget(self.file_browser)
        self.file_browser_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | 
                                               Qt.DockWidgetArea.RightDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.file_browser_dock)
        
        # Center - Image viewer
        self.image_viewer = ImageViewer()
        main_splitter.addWidget(self.image_viewer)
        
        # Right panel - Metadata
        self.metadata_panel = MetadataPanel()
        self.metadata_panel.generate_uid_requested.connect(self.generate_picture_uid)
        self.metadata_panel.write_uid_requested.connect(self.write_picture_uid)
        main_splitter.addWidget(self.metadata_panel)
        
        # Set splitter proportions
        main_splitter.setSizes([900, 500])
        
        main_layout.addWidget(main_splitter)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
    
    def _setup_actions(self):
        """Setup actions"""
        # File actions
        self.open_folder_action = QAction("Open Folder", self)
        self.open_folder_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_folder_action.triggered.connect(self.open_folder)
        
        # Export actions
        self.export_image_action = QAction("Export Current Image", self)
        self.export_image_action.setShortcut(QKeySequence("Ctrl+E"))
        self.export_image_action.triggered.connect(self._export_current_image)
        self.export_image_action.setEnabled(False)
        
        self.export_metadata_action = QAction("Export Metadata", self)
        self.export_metadata_action.setShortcut(QKeySequence("Ctrl+M"))
        self.export_metadata_action.triggered.connect(self._export_metadata)
        self.export_metadata_action.setEnabled(False)
        
        self.bulk_export_action = QAction("Bulk Export All", self)
        self.bulk_export_action.setShortcut(QKeySequence("Ctrl+Shift+E"))
        self.bulk_export_action.triggered.connect(self._bulk_export)
        self.bulk_export_action.setEnabled(False)
        
        # View actions
        self.fit_to_view_action = QAction("Fit to View", self)
        self.fit_to_view_action.setShortcut(QKeySequence("F"))
        self.fit_to_view_action.triggered.connect(self.image_viewer.fit_to_view)
        
        self.reset_zoom_action = QAction("Reset Zoom", self)
        self.reset_zoom_action.setShortcut(QKeySequence("R"))
        self.reset_zoom_action.triggered.connect(self.image_viewer.reset_zoom)
        
        # Navigation actions
        self.prev_file_action = QAction("Previous File", self)
        self.prev_file_action.setShortcut(QKeySequence(Qt.Key.Key_Left))
        self.prev_file_action.triggered.connect(self.file_browser.select_previous)
        
        self.next_file_action = QAction("Next File", self)
        self.next_file_action.setShortcut(QKeySequence(Qt.Key.Key_Right))
        self.next_file_action.triggered.connect(self.file_browser.select_next)
        
        # Help actions
        self.about_action = QAction("About", self)
        self.about_action.triggered.connect(self._show_about)
    
    def _setup_toolbar(self):
        """Setup toolbar"""
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        
        toolbar.addAction(self.open_folder_action)
        toolbar.addSeparator()
        toolbar.addAction(self.export_image_action)
        toolbar.addAction(self.export_metadata_action)
        toolbar.addAction(self.bulk_export_action)
        toolbar.addSeparator()
        toolbar.addAction(self.fit_to_view_action)
        toolbar.addAction(self.reset_zoom_action)
    
    def _setup_menubar(self):
        """Setup menu bar"""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("File")
        file_menu.addAction(self.open_folder_action)
        file_menu.addSeparator()
        file_menu.addAction(self.export_image_action)
        file_menu.addAction(self.export_metadata_action)
        file_menu.addAction(self.bulk_export_action)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)
        
        # View menu
        view_menu = menubar.addMenu("View")
        view_menu.addAction(self.fit_to_view_action)
        view_menu.addAction(self.reset_zoom_action)
        view_menu.addSeparator()
        view_menu.addAction(self.prev_file_action)
        view_menu.addAction(self.next_file_action)
        view_menu.addSeparator()
        toggle_browser = self.file_browser_dock.toggleViewAction()
        toggle_browser.setText("Show File Browser")
        view_menu.addAction(toggle_browser)
        
        # Help menu
        help_menu = menubar.addMenu("Help")
        help_menu.addAction(self.about_action)
    
    def open_folder(self):
        """Open a folder containing DICOM or image files"""
        folder = QFileDialog.getExistingDirectory(self, "Select Image Folder")
        if folder:
            self.current_folder = Path(folder)
            self.load_files()
    
    def load_files(self):
        """Load DICOM and image files from current folder"""
        if not self.current_folder:
            return
        
        # Store current directory
        self.current_directory = self.current_folder
        
        # Load files from directory
        self.file_list = []
        self.loaded_files = {}
        
        dicom_exts = ['.dcm', '.dicom']
        image_exts = ['.tiff', '.tif', '.png', '.jpg', '.jpeg', '.bmp', '.gif']
        
        for file_path in self.current_folder.rglob('*'):
            if file_path.is_file():
                ext = file_path.suffix.lower()
                
                # Try DICOM first
                if ext in dicom_exts or ext == '':
                    try:
                        dicom_file = DicomFile(str(file_path))
                        self.file_list.append(str(file_path))
                        self.loaded_files[str(file_path)] = dicom_file
                    except Exception as e:
                        logger.error(f"Failed to load DICOM: {file_path}: {e}")
                        # If DICOM fails and no extension, try as image
                        if ext == '':
                            try:
                                image_file = RegularImageFile(str(file_path))
                                self.file_list.append(str(file_path))
                                self.loaded_files[str(file_path)] = image_file
                            except Exception as e2:
                                logger.error(f"Failed to load as image: {file_path}: {e2}")
                elif ext in image_exts:
                    try:
                        image_file = RegularImageFile(str(file_path))
                        self.file_list.append(str(file_path))
                        self.loaded_files[str(file_path)] = image_file
                    except Exception as e:
                        logger.error(f"Failed to load image: {file_path}: {e}")
        
        # Update UI
        self.file_browser.load_file_list(self.file_list)
        
        if self.file_list:
            self.status_bar.showMessage(f"Loaded {len(self.file_list)} files")
        else:
            self.status_bar.showMessage("No supported files found")
    
    def display_file(self, index: int):
        """Display selected file"""
        if 0 <= index < len(self.file_list):
            file_path = self.file_list[index]
            self.current_file = self.loaded_files.get(file_path)
            
            if self.current_file:
                # Update image viewer
                self.image_viewer.display_image(self.current_file)
                
                # Update metadata panel (only for DICOM files)
                if isinstance(self.current_file, DicomFile):
                    self.metadata_panel.update_metadata(self.current_file)
                else:
                    # Show basic metadata for regular images
                    self.metadata_panel.update_metadata(None)
                    # Could optionally display image metadata here
                
                file_type = "DICOM" if isinstance(self.current_file, DicomFile) else "Image"
                self.status_bar.showMessage(f"Viewing {file_type}: {Path(file_path).name}")
                
                # Enable/disable actions based on file type
                self.export_image_action.setEnabled(True)
                self.bulk_export_action.setEnabled(bool(self.loaded_files))
    
    def generate_picture_uid(self):
        """Generate Picture UID for current file"""
        if self.current_file:
            uid = self.current_file.generate_picture_uid()
            if isinstance(self.current_file, DicomFile):
                self.metadata_panel.set_picture_uid(uid)
            self.status_bar.showMessage(f"Generated Picture UID: {uid}")
    
    def write_picture_uid(self):
        """Write Picture UID to file"""
        if self.current_file and self.current_file.picture_uid:
            try:
                output_path = Path(self.file_list[self.file_browser.list_widget.currentRow()])
                
                if isinstance(self.current_file, DicomFile):
                    output_path = output_path.parent / f"{output_path.stem}_with_uid.dcm"
                    self.current_file.write_picture_uid(output_path)
                    self.metadata_panel.mark_uid_written()
                    self.status_bar.showMessage(f"Picture UID written to: {output_path.name}")
                else:
                    # For regular images, save metadata to JSON sidecar
                    self.current_file.write_picture_uid(output_path.parent / output_path.stem)
                    self.status_bar.showMessage(f"Picture UID metadata saved for: {output_path.name}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to write Picture UID: {e}")
    
    def _export_current_image(self):
        """Export current image"""
        if not self.current_file:
            return
        
        try:
            # Get export directory
            export_dir = QFileDialog.getExistingDirectory(
                self,
                "Select Export Directory",
                str(self.export_config.export_dir)
            )
            
            if export_dir:
                export_path = Path(export_dir)
                self.export_config.export_dir = export_path
                
                # Create exporter
                exporter = Exporter(export_path)
                
                # Generate Picture UID if needed
                if not self.current_file.picture_uid:
                    self.current_file.generate_picture_uid()
                
                picture_uid = self.current_file.picture_uid
                
                # Export image
                image_path = exporter.export_single_image(self.current_file)
                
                QMessageBox.information(
                    self,
                    "Export Complete",
                    f"Image exported to:\n{image_path}"
                )
                
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export image: {e}")
    
    def _export_metadata(self):
        """Export metadata for all files"""
        if not self.file_list:
            return
        
        try:
            # Get export directory
            export_dir = QFileDialog.getExistingDirectory(
                self,
                "Select Export Directory",
                str(self.export_config.export_dir)
            )
            
            if export_dir:
                export_path = Path(export_dir)
                self.export_config.export_dir = export_path
                
                # Get export options
                options = self.metadata_panel.get_export_options()
                
                # Create exporter
                exporter = Exporter(export_path)
                
                # Export metadata
                results = exporter.export_metadata(
                    self.loaded_files.values(),
                    deidentify=options["deidentify"],
                    export_csv=options["export_csv"]
                )
                
                message = "Metadata exported to:\n"
                for format_name, path in results.items():
                    message += f"- {path}\n"
                
                QMessageBox.information(self, "Export Complete", message)
                
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export metadata: {e}")
    
    def _bulk_export(self):
        """Bulk export all files"""
        if not self.current_directory:
            return
        
        try:
            # Get export directory
            export_dir = QFileDialog.getExistingDirectory(
                self,
                "Select Export Directory",
                str(self.export_config.export_dir)
            )
            
            if export_dir:
                export_path = Path(export_dir)
                self.export_config.export_dir = export_path
                
                # Get export options
                options = self.metadata_panel.get_export_options()
                
                # Ask about writing UIDs
                write_uids = False
                reply = QMessageBox.question(
                    self,
                    "Write Picture UIDs",
                    "Write generated Picture UIDs to DICOM files?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    write_uids = True
                
                # Create progress dialog
                progress = QProgressDialog(
                    "Exporting files...",
                    "Cancel",
                    0,
                    len(self.loaded_files),
                    self
                )
                progress.setWindowModality(Qt.WindowModality.WindowModal)
                progress.setAutoClose(False)
                
                # Progress callback
                def update_progress(current, total, message):
                    progress.setValue(current)
                    progress.setLabelText(message)
                    if progress.wasCanceled():
                        return False
                    return True
                
                # Create exporter
                exporter = Exporter(export_path)
                
                # Perform bulk export manually since we have individual files
                results = {
                    "images": [],
                    "metadata": None,
                    "errors": []
                }
                
                file_objects = list(self.loaded_files.values())
                
                # Process each file
                for i, file_obj in enumerate(file_objects):
                    try:
                        # Update progress
                        if not update_progress(i + 1, len(file_objects), f"Processing {Path(file_obj.file_path).name}"):
                            break  # User canceled
                        
                        # Only export DICOM files for now
                        if hasattr(file_obj, 'dataset'):  # DICOM file
                            try:
                                # Pre-load pixel data to cache the full dataset (fixes first-try failures)
                                logger.debug(f"Pre-loading pixel data for {Path(file_obj.file_path).name}")
                                _ = file_obj.get_pixel_array()
                                logger.debug(f"Pixel data loaded successfully for {Path(file_obj.file_path).name}")
                                
                                # Ensure Picture UID
                                if not file_obj.picture_uid:
                                    logger.debug(f"Generating Picture UID for {Path(file_obj.file_path).name}")
                                    file_obj.generate_picture_uid()
                                    if write_uids:
                                        logger.debug(f"Writing Picture UID to DICOM for {Path(file_obj.file_path).name}")
                                        file_obj.write_picture_uid(save=False)  # Skip saving to avoid DICOM reading issues
                                        logger.debug(f"Picture UID written successfully for {Path(file_obj.file_path).name}")
                                
                                # Export image (retry logic now handled at pixel array level)
                                logger.debug(f"Starting image export for {Path(file_obj.file_path).name}")
                                image_path = exporter.export_single_image(file_obj)
                                logger.debug(f"Image export completed for {Path(file_obj.file_path).name}")
                                results["images"].append(str(image_path))
                            except Exception as e:
                                logger.debug(f"Exception during export of {Path(file_obj.file_path).name}: {e}")
                                raise e
                        
                    except Exception as e:
                        error_msg = f"Failed to export {Path(file_obj.file_path).name}: {str(e)}"
                        results["errors"].append(error_msg)
                        logger.error(error_msg)
                        print(f"DEBUG: Export error for {Path(file_obj.file_path).name}: {e}")
                
                # Export metadata for DICOM files
                dicom_files = [f for f in file_objects if hasattr(f, 'dataset')]
                if dicom_files:
                    try:
                        metadata_results = exporter.export_metadata(
                            dicom_files,
                            deidentify=options["deidentify"],
                            export_csv=options["export_csv"]
                        )
                        results["metadata"] = metadata_results
                    except Exception as e:
                        results["errors"].append(f"Failed to export metadata: {e}")
                        logger.error(f"Metadata export failed: {e}")
                
                progress.close()
                
                # Show results
                message = f"Export complete!\n\n"
                message += f"Images exported: {len(results['images'])}\n"
                if results['metadata']:
                    message += f"Metadata: {', '.join(results['metadata'].keys())}\n"
                if results['errors']:
                    message += f"\nErrors: {len(results['errors'])}\n"
                    # Show first few errors for debugging
                    for i, error in enumerate(results['errors'][:3]):
                        message += f"  {i+1}. {error}\n"
                    if len(results['errors']) > 3:
                        message += f"  ... and {len(results['errors']) - 3} more\n"
                
                QMessageBox.information(self, "Export Complete", message)
                
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to perform bulk export: {e}")
    
    def _show_about(self):
        """Show about dialog"""
        QMessageBox.about(
            self,
            "About DICOM Reader/Writer",
            "DICOM Fundus Reader/Writer\n\n"
            "A PyQt application for viewing and exporting\n"
            "ophthalmic DICOM images with metadata management.\n\n"
            "Features:\n"
            "- DICOM image viewing with zoom/pan\n"
            "- Picture UID generation and persistence\n"
            "- TIFF image export\n"
            "- JSON/CSV metadata export\n"
            "- PHI de-identification\n\n"
            "Created with PyQt6 and pydicom"
        )
    
    def _restore_settings(self):
        """Restore application settings"""
        # Window geometry
        geometry = self.settings.value("window_geometry")
        if geometry:
            self.restoreGeometry(geometry)
        
        # Window state
        state = self.settings.value("window_state")
        if state:
            self.restoreState(state)
    
    def closeEvent(self, event):
        """Save settings on close"""
        self.settings.setValue("window_geometry", self.saveGeometry())
        self.settings.setValue("window_state", self.saveState())
        event.accept()
