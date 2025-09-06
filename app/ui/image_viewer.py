"""
Image viewer widget with zoom and pan capabilities
"""
from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsTextItem, QGraphicsPixmapItem, QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, pyqtSignal, QRectF
from PyQt6.QtGui import QPixmap, QImage, QPainter, QBrush, QColor, QWheelEvent, QMouseEvent
import numpy as np
from typing import Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.dicom_io import DicomFile
    from app.core.regular_image import RegularImageFile


class ImageViewer(QGraphicsView):
    """Custom QGraphicsView for DICOM image display with zoom/pan"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene()
        self.setScene(self.scene)
        
        self.pixmap_item = None
        self.current_pixmap = None
        self.laterality = None
        
        # Setup view properties
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        # Zoom factors
        self.zoom_factor = 1.15
        self.max_zoom = 10.0
        self.min_zoom = 0.1
        self.current_zoom = 1.0
        
    def display_image(self, file_obj: Union['DicomFile', 'RegularImageFile']):
        """Display image from DICOM or regular image file"""
        if not file_obj:
            self.clear_image()
            return
        
        try:
            # Get pixel array
            pixel_array = file_obj.get_pixel_array()
            if pixel_array is None:
                self._show_error_placeholder("No pixel data available")
                return
            
            # Get laterality for DICOM files
            laterality = None
            if hasattr(file_obj, 'metadata') and isinstance(file_obj.metadata, dict):
                laterality = file_obj.metadata.get('image_laterality')
            
            self.set_image(pixel_array, laterality)
            
        except Exception as e:
            # Show error placeholder instead of crashing
            error_msg = f"Cannot display image: {str(e)}"
            self._show_error_placeholder(error_msg)
            print(f"Error displaying {getattr(file_obj, 'file_path', 'unknown file')}: {e}")
    
    def set_image(self, pixel_array: np.ndarray, laterality: str = None):
        """Set image from numpy array"""
        self.laterality = laterality
        
        # Clear previous image
        self.scene.clear()
        
        # Convert numpy array to QPixmap
        if len(pixel_array.shape) == 3:
            # RGB image
            height, width, channels = pixel_array.shape
            bytes_per_line = channels * width
            qimage = QImage(pixel_array.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
        else:
            # Grayscale
            height, width = pixel_array.shape
            
            # Normalize to 8-bit if needed
            if pixel_array.dtype != np.uint8:
                min_val = pixel_array.min()
                max_val = pixel_array.max()
                if max_val > min_val:
                    pixel_array = ((pixel_array - min_val) * 255 / (max_val - min_val)).astype(np.uint8)
                else:
                    pixel_array = np.zeros_like(pixel_array, dtype=np.uint8)
            
            bytes_per_line = width
            qimage = QImage(pixel_array.data, width, height, bytes_per_line, QImage.Format.Format_Grayscale8)
        
        self.current_pixmap = QPixmap.fromImage(qimage)
        self.pixmap_item = self.scene.addPixmap(self.current_pixmap)
        
        # Add laterality badge if present
        if laterality:
            self._add_laterality_badge(laterality)
        
        # Fit image to view
        self.fit_to_view()
    
    def _add_laterality_badge(self, laterality: str):
        """Add laterality indicator to image"""
        from PyQt6.QtWidgets import QGraphicsTextItem
        from PyQt6.QtGui import QFont, QColor
        
        # Create text item
        text_item = QGraphicsTextItem(laterality)
        font = QFont("Arial", 24, QFont.Weight.Bold)
        text_item.setFont(font)
        text_item.setDefaultTextColor(QColor(255, 255, 0))  # Yellow
        
        # Position in top-left corner
        text_item.setPos(10, 10)
        self.scene.addItem(text_item)
    
    def fit_to_view(self):
        """Fit image to view"""
        if self.pixmap_item:
            self.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
            self.current_zoom = 1.0
    
    def wheelEvent(self, event: QWheelEvent):
        """Handle mouse wheel for zooming"""
        if self.pixmap_item:
            # Get zoom direction
            delta = event.angleDelta().y()
            
            if delta > 0:
                # Zoom in
                if self.current_zoom < self.max_zoom:
                    self.scale(self.zoom_factor, self.zoom_factor)
                    self.current_zoom *= self.zoom_factor
            else:
                # Zoom out
                if self.current_zoom > self.min_zoom:
                    factor = 1.0 / self.zoom_factor
                    self.scale(factor, factor)
                    self.current_zoom *= factor
    
    def reset_zoom(self):
        """Reset zoom to 100%"""
        if self.current_zoom != 1.0:
            factor = 1.0 / self.current_zoom
            self.scale(factor, factor)
            self.current_zoom = 1.0
    
    def clear_image(self):
        """Clear the displayed image"""
        self.scene.clear()
        self.pixmap_item = None
        self.current_pixmap = None
        self.laterality = None
        self.current_zoom = 1.0

    def _show_error_placeholder(self, error_msg: str):
        """Show error placeholder instead of crashing"""
        from PyQt6.QtGui import QPixmap, QPainter, QFont, QColor
        from PyQt6.QtCore import Qt
        
        # Clear scene first
        self.scene.clear()
        
        # Create a placeholder image
        pixmap = QPixmap(400, 300)
        pixmap.fill(QColor(240, 240, 240))
        
        painter = QPainter(pixmap)
        painter.setPen(QColor(100, 100, 100))
        font = QFont()
        font.setPointSize(12)
        painter.setFont(font)
        
        # Draw error message
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, 
                        f"⚠️ Error Loading Image\n\n{error_msg}")
        painter.end()
        
        # Add to scene
        self.pixmap_item = self.scene.addPixmap(pixmap)
        self.current_pixmap = pixmap
        self.current_zoom = 1.0
