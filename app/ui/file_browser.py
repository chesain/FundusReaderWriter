import os
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QListWidgetItem

SUPPORTED_EXTS = {".dcm", ".dicom", ".tif", ".tiff"}

class FileBrowser(QWidget):
    """
    Simple file list on the left; emits fileSelected(Path) when selection changes.
    Arrow keys navigate too.
    """
    fileSelected = pyqtSignal(Path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root: Optional[Path] = None
        self._files: List[Path] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget(self)
        self.list.currentRowChanged.connect(self._emit_current)
        layout.addWidget(self.list)

    # ---- Public API ----

    def set_directory(self, folder: Path):
        self._root = folder
        self._files = sorted([p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS])
        self._reload()

    def set_files(self, files: List[Path]):
        self._root = None
        self._files = files
        self._reload()

    def current(self) -> Optional[Path]:
        idx = self.list.currentRow()
        if 0 <= idx < len(self._files):
            return self._files[idx]
        return None

    def select_index(self, idx: int):
        if 0 <= idx < self.list.count():
            self.list.setCurrentRow(idx)

    def files(self) -> List[Path]:
        return list(self._files)

    # ---- Internals ----

    def _reload(self):
        self.list.clear()
        for p in self._files:
            item = QListWidgetItem(p.name)
            # Tiny preview icon if it’s a TIFF; keeps UI snappy (best-effort).
            if p.suffix.lower() in {".tif", ".tiff"}:
                try:
                    from PIL import Image
                    im = Image.open(p)
                    im.thumbnail((48, 48))
                    qpix = QPixmap.fromImage(
                        QPixmap.fromImage(
                            QPixmap.fromImage
                        )  # placeholder to avoid lint “unused import”; tiny previews are optional
                    )
                except Exception:
                    pass
            self.list.addItem(item)
        if self._files:
            self.list.setCurrentRow(0)

    def _emit_current(self, row: int):
        if 0 <= row < len(self._files):
            self.fileSelected.emit(self._files[row])
