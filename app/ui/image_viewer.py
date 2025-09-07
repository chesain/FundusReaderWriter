# app/ui/image_viewer.py
from __future__ import annotations

from typing import Optional

import numpy as np
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QImage, QPixmap, QAction, QKeySequence, QWheelEvent
from PyQt6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView


class ImageViewer(QGraphicsView):
    """
    QGraphicsView-based image viewer with wheel zoom, hand panning,
    and toolbar/shortcut actions (Zoom In/Out, Fit to View).
    Public API:
      - set_image(np.ndarray)
      - actions: act_zoom_in, act_zoom_out, act_fit
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        # Scene & pixmap item
        self._scene = QGraphicsScene(self)
        self._pix_item = QGraphicsPixmapItem()
        self._scene.addItem(self._pix_item)
        self.setScene(self._scene)

        # Interaction / render hints
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        # (Optional) antialiasing etc. Commented to avoid QtGui import churn.
        # from PyQt6.QtGui import QPainter
        # self.setRenderHints(self.renderHints() | QPainter.RenderHint.SmoothPixmapTransform)

        # ---- Actions (use string or StandardKey shortcuts; no enum math) ----
        self.act_fit = QAction("Fit to View", self)
        self.act_fit.setShortcut(QKeySequence("Ctrl+0"))    # On mac this maps to Cmd+0
        self.act_fit.triggered.connect(self.fit_to_view)
        self.addAction(self.act_fit)

        self.act_zoom_in = QAction("Zoom In", self)
        self.act_zoom_in.setShortcut(QKeySequence.StandardKey.ZoomIn)  # Ctrl/Cmd + '+'
        self.act_zoom_in.triggered.connect(lambda: self._zoom(1.25))
        self.addAction(self.act_zoom_in)

        self.act_zoom_out = QAction("Zoom Out", self)
        self.act_zoom_out.setShortcut(QKeySequence.StandardKey.ZoomOut)  # Ctrl/Cmd + '-'
        self.act_zoom_out.triggered.connect(lambda: self._zoom(0.8))
        self.addAction(self.act_zoom_out)

    # ---------- Public API ----------

    def set_image(self, arr: Optional[np.ndarray]) -> None:
        """Accepts uint8 RGB (H,W,3) or uint8 gray (H,W)."""
        if arr is None:
            self._pix_item.setPixmap(QPixmap())
            self._scene.setSceneRect(QRectF())
            return

        if arr.ndim == 2:
            fmt = QImage.Format.Format_Grayscale8
            h, w = arr.shape
            qimg = QImage(arr.data, w, h, arr.strides[0], fmt)
        elif arr.ndim == 3 and arr.shape[2] == 3:
            if arr.dtype != np.uint8:
                arr = arr.astype(np.uint8, copy=False)
            h, w, _ = arr.shape
            qimg = QImage(arr.data, w, h, arr.strides[0], QImage.Format.Format_RGB888)
        else:
            raise ValueError("Unsupported array shape; expected (H,W) or (H,W,3) uint8")

        self._pix_item.setPixmap(QPixmap.fromImage(qimg))
        self._scene.setSceneRect(self._pix_item.boundingRect())
        self.fit_to_view()

    # ---------- Interaction ----------

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._pix_item.pixmap().isNull():
            return
        self._zoom(1.25 if event.angleDelta().y() > 0 else 0.8)

    def _zoom(self, factor: float) -> None:
        self.scale(factor, factor)

    def fit_to_view(self) -> None:
        if self._pix_item.pixmap().isNull():
            return
        self.fitInView(self._pix_item, Qt.AspectRatioMode.KeepAspectRatio)
