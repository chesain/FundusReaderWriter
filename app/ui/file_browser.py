"""
File browser widget for DICOM files
"""
from PyQt6.QtWidgets import (QListWidget, QListWidgetItem, QWidget, QVBoxLayout,
                            QLabel, QHBoxLayout, QPushButton, QComboBox)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from app.core.dicom_io import DicomFile
from app.core.regular_image import RegularImageFile
from PyQt6.QtGui import QIcon, QPixmap, QImage
from typing import List, Optional
import numpy as np
from pathlib import Path


class FileBrowser(QWidget):
    """File browser for DICOM files with thumbnail support"""
    
    # Signals
    file_selected = pyqtSignal(int)  # Emits index of selected file
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.file_list = []
        self.current_index = -1
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the UI"""
        layout = QVBoxLayout(self)
        
        # Header
        header_layout = QHBoxLayout()
        self.count_label = QLabel("No files loaded")
        header_layout.addWidget(self.count_label)
        header_layout.addStretch()
        
        # Navigation buttons
        self.prev_btn = QPushButton("← Previous")
        self.prev_btn.setEnabled(False)
        self.prev_btn.clicked.connect(self.select_previous)
        
        self.next_btn = QPushButton("Next →")
        self.next_btn.setEnabled(False)
        self.next_btn.clicked.connect(self.select_next)
        
        header_layout.addWidget(self.prev_btn)
        header_layout.addWidget(self.next_btn)
        
        layout.addLayout(header_layout)
        
        # Filter for supported files
        self.filter_combo = QComboBox()
        self.filter_combo.addItems([
            "All Supported Files",
            "DICOM Files (*.dcm)",
            "Image Files (*.tiff *.png *.jpg *.jpeg)",
            "All Files (*.*)"
        ])
        self.filter_combo.currentTextChanged.connect(self._apply_filter)
        
        layout.addWidget(self.filter_combo)
        
        # File list
        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(64, 64))
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.currentRowChanged.connect(self._on_selection_changed)
        layout.addWidget(self.list_widget)
    
    def load_file_list(self, files: List[str]):
        """Load list of files"""
        self.file_list = files
        self.list_widget.clear()
        
        # Add items to list
        for i, filename in enumerate(files):
            item = QListWidgetItem(filename)
            item.setData(Qt.ItemDataRole.UserRole, i)  # Store index
            
            # Create placeholder thumbnail
            pixmap = self._create_placeholder_thumbnail()
            item.setIcon(QIcon(pixmap))
            
            self.list_widget.addItem(item)
        
        # Update count
        count = len(files)
        if count > 0:
            self.count_label.setText(f"{count} file(s) loaded")
            self.prev_btn.setEnabled(True)
            self.next_btn.setEnabled(True)
        else:
            self.count_label.setText("No files loaded")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
    
    def set_thumbnail(self, index: int, pixel_array: np.ndarray):
        """Set thumbnail for a specific file"""
        if 0 <= index < self.list_widget.count():
            item = self.list_widget.item(index)
            
            # Create thumbnail from pixel array
            thumbnail = self._create_thumbnail(pixel_array, size=64)
            
            # Convert to QPixmap
            if len(pixel_array.shape) == 3:
                # RGB
                height, width = thumbnail.shape[:2]
                bytes_per_line = 3 * width
                qimage = QImage(thumbnail.data, width, height, bytes_per_line, 
                              QImage.Format.Format_RGB888)
            else:
                # Grayscale
                height, width = thumbnail.shape
                bytes_per_line = width
                qimage = QImage(thumbnail.data, width, height, bytes_per_line,
                              QImage.Format.Format_Grayscale8)
            
            pixmap = QPixmap.fromImage(qimage)
            item.setIcon(QIcon(pixmap))
    
    def _create_thumbnail(self, pixel_array: np.ndarray, size: int = 64) -> np.ndarray:
        """Create thumbnail from pixel array"""
        # Calculate resize factor
        height, width = pixel_array.shape[:2]
        scale = min(size / width, size / height)
        
        new_width = int(width * scale)
        new_height = int(height * scale)
        
        # Simple downsampling (for better quality, use proper image resizing)
        step_y = max(1, height // new_height)
        step_x = max(1, width // new_width)
        
        if len(pixel_array.shape) == 3:
            thumbnail = pixel_array[::step_y, ::step_x, :]
        else:
            thumbnail = pixel_array[::step_y, ::step_x]
            
            # Normalize to 8-bit
            if thumbnail.dtype != np.uint8:
                min_val = thumbnail.min()
                max_val = thumbnail.max()
                if max_val > min_val:
                    thumbnail = ((thumbnail - min_val) * 255 / (max_val - min_val)).astype(np.uint8)
                else:
                    thumbnail = np.zeros_like(thumbnail, dtype=np.uint8)
        
        return thumbnail
    
    def _apply_filter(self, filter_text: str):
        """Apply file filter"""
        # Re-filter the current file list when filter changes
        if hasattr(self, 'file_list') and self.file_list:
            # For now, just keep the current list
            # In a full implementation, this would filter the display
            pass
    
    def _create_placeholder_thumbnail(self) -> QPixmap:
        """Create placeholder thumbnail"""
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.lightGray)
        return pixmap
    
    def _on_item_clicked(self, item: QListWidgetItem):
        """Handle item click"""
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is not None:
            self.file_selected.emit(index)
    
    def _on_selection_changed(self, row: int):
        """Handle selection change"""
        if row >= 0:
            self.current_index = row
            self._update_navigation_buttons()
    
    def _update_navigation_buttons(self):
        """Update navigation button states"""
        count = self.list_widget.count()
        if count == 0:
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
        else:
            self.prev_btn.setEnabled(self.current_index > 0)
            self.next_btn.setEnabled(self.current_index < count - 1)
    
    def select_file(self, index: int):
        """Select file by index"""
        if 0 <= index < self.list_widget.count():
            self.list_widget.setCurrentRow(index)
            self.file_selected.emit(index)
    
    def select_previous(self):
        """Select previous file"""
        if self.current_index > 0:
            self.select_file(self.current_index - 1)
    
    def select_next(self):
        """Select next file"""
        if self.current_index < self.list_widget.count() - 1:
            self.select_file(self.current_index + 1)
    
    def get_current_index(self) -> int:
        """Get current selected index"""
        return self.current_index
    
    def clear(self):
        """Clear file list"""
        self.list_widget.clear()
        self.file_list = []
        self.current_index = -1
        self.count_label.setText("No files loaded")
        self.prev_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
