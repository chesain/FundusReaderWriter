# app/ui/main_window.py
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
from PIL import Image

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox,
    QSplitter, QListWidget, QListWidgetItem, QToolBar, QStatusBar, QLabel
)

from app.ui.image_viewer import ImageViewer
from app.ui.metadata_panel import MetadataPanel
from app.core.dicom_io import DicomFile, initialize_dicom_environment
from app.core.tiff_reader import TIFFReader  # <- class name in your file

log = logging.getLogger(__name__)


# ---------- small helpers ----------------------------------------------------

def _sanitize_stem(s: str) -> str:
    """Make a filename stem safe while keeping DICOM-like dots."""
    s = s.strip()
    # Replace path separators and weird whitespace
    s = s.replace("/", "_").replace("\\", "_")
    # Allow digits, letters, dot, dash, underscore; collapse the rest to _
    s = re.sub(r"[^0-9A-Za-z._-]", "_", s)
    # Avoid extremely long names
    return s[:200] if len(s) > 200 else s


def _unique_path(dir_: Path, stem: str, suffix: str) -> Path:
    """Return a non-existing path by appending -2, -3, ... if needed."""
    p = dir_ / f"{stem}{suffix}"
    if not p.exists():
        return p
    i = 2
    while True:
        p2 = dir_ / f"{stem}-{i}{suffix}"
        if not p2.exists():
            return p2
        i += 1


def _norm8(arr: np.ndarray) -> np.ndarray:
    """Convert an array to uint8 for saving as TIFF (keeping RGB/gray)."""
    if arr.dtype == np.uint8:
        return arr
    a = arr.astype(np.float32)
    mn = float(a.min())
    mx = float(a.max())
    if mx <= mn:
        return np.zeros_like(a, dtype=np.uint8)
    a = (a - mn) * (255.0 / (mx - mn))
    a = np.clip(a, 0, 255).astype(np.uint8)
    return a


def _looks_like_dicom(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            f.seek(128)
            return f.read(4) == b"DICM"
    except Exception:
        return False


# ---------- main window ------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        initialize_dicom_environment()

        self.setWindowTitle("DICOM / TIFF Viewer")
        self.resize(1400, 900)

        # Left: file list
        self.list_widget = QListWidget(self)
        self.list_widget.itemSelectionChanged.connect(self._on_select_file)

        # Center: image viewer
        self.viewer = ImageViewer(self)

        # Right: metadata panel
        self.meta_panel = MetadataPanel(self)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self.list_widget)
        splitter.addWidget(self.viewer)
        splitter.addWidget(self.meta_panel)
        # Heavier weight for the viewer; smaller for list & metadata
        splitter.setStretchFactor(0, 1)   # file list
        splitter.setStretchFactor(1, 10)  # viewer
        splitter.setStretchFactor(2, 2)   # metadata panel
        self.splitter = splitter  # keep a handle for setSizes() later

        container = QWidget(self)
        lay = QVBoxLayout(container)
        lay.addWidget(splitter)
        self.setCentralWidget(container)


        # Build a minimal View menu (Fit / Zoom) using actions from ImageViewer
        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self.viewer.act_fit)
        view_menu.addAction(self.viewer.act_zoom_in)
        view_menu.addAction(self.viewer.act_zoom_out)


        # Toolbar
        tb = QToolBar("Main", self)
        self.addToolBar(tb)

        act_open = QAction("Open Image…", self)
        act_open.triggered.connect(self._open_single_file)
        tb.addAction(act_open)

        act_open_folder = QAction("Open Folder…", self)
        act_open_folder.triggered.connect(self._open_folder)
        tb.addAction(act_open_folder)

        tb.addSeparator()

        act_prev = QAction("Previous", self)
        act_prev.triggered.connect(self._prev)
        tb.addAction(act_prev)

        act_next = QAction("Next", self)
        act_next.triggered.connect(self._next)
        tb.addAction(act_next)

        tb.addSeparator()

        act_export_current = QAction("Export Current", self)
        act_export_current.triggered.connect(self._export_current)
        tb.addAction(act_export_current)

        act_bulk = QAction("Bulk Export…", self)
        act_bulk.triggered.connect(self._bulk_export)
        tb.addAction(act_bulk)

        tb.addSeparator()
        tb.addAction(self.viewer.act_fit)
        tb.addAction(self.viewer.act_zoom_in)
        tb.addAction(self.viewer.act_zoom_out)

        self.setStatusBar(QStatusBar(self))
        log.info("MainWindow ready")

        # Keep an in-memory list of absolute Paths
        self._paths: List[Path] = []

        QTimer.singleShot(0, self._set_initial_split_sizes)

    # ---------- file loading --------------------------------------------------

    def _open_single_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open DICOM or TIFF",
            "", "Images (*.dcm *.dicom *.tif *.tiff);;All files (*.*)"
        )
        if not path:
            return
        self._paths = [Path(path)]
        self._populate_file_list()
        self._select_index(0)

    def _open_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open Folder")
        if not folder:
            return
        p = Path(folder)
        # Order: .dcm then .tif/.tiff, plus extensionless with DICM
        dcm = list(p.rglob("*.dcm"))
        dcm += list(p.rglob("*.dicom"))
        tif = list(p.rglob("*.tif")) + list(p.rglob("*.tiff"))
        extless = [q for q in p.rglob("*") if q.is_file() and q.suffix == "" and _looks_like_dicom(q)]
        self._paths = sorted(dcm + tif + extless)
        self._populate_file_list()
        if self._paths:
            self._select_index(0)

    def _populate_file_list(self) -> None:
        self.list_widget.clear()
        for p in self._paths:
            QListWidgetItem(p.name, self.list_widget)

    def _on_select_file(self) -> None:
        idx = self.list_widget.currentRow()
        if idx < 0 or idx >= len(self._paths):
            return
        self._load_and_show(self._paths[idx])

    def _select_index(self, idx: int) -> None:
        if 0 <= idx < len(self._paths):
            self.list_widget.setCurrentRow(idx)

    def _prev(self) -> None:
        idx = self.list_widget.currentRow()
        if idx <= 0:
            return
        self._select_index(idx - 1)

    def _next(self) -> None:
        idx = self.list_widget.currentRow()
        if idx < 0 or idx >= len(self._paths) - 1:
            return
        self._select_index(idx + 1)

    # ---------- read + show ---------------------------------------------------

    def _load_and_show(self, path: Path) -> None:
        try:
            arr, meta = self._read_pixels_and_metadata(path)
            self.viewer.set_image(arr)
            self.viewer.fit_to_view()
            self.meta_panel.set_metadata(meta or {})
            self.statusBar().showMessage(f"Loaded {path.name}", 4000)
        except Exception as e:
            log.exception("Failed to load %s", path)
            QMessageBox.critical(self, "Error", f"Failed to load {path.name}: {e}")

    def _read_pixels_and_metadata(self, path: Path) -> Tuple[np.ndarray, Dict[str, Any]]:
        suffix = path.suffix.lower()
        # DICOM if .dcm/.dicom or signature
        if suffix in (".dcm", ".dicom") or (suffix == "" and _looks_like_dicom(path)):
            dcm = DicomFile(str(path))
            ds = dcm.dataset
            arr = dcm.get_pixel_array()

            # Convert YBR* → RGB if needed
            try:
                from pydicom.pixel_data_handlers.util import convert_color_space
                pi = str(getattr(ds, "PhotometricInterpretation", "")).upper()
                if isinstance(arr, np.ndarray) and arr.ndim == 3 and arr.shape[2] == 3 and pi.startswith("YBR"):
                    log.info("Converting %s -> RGB", pi)
                    arr = convert_color_space(arr, pi, "RGB")
            except Exception:
                log.debug("Color conversion skipped", exc_info=True)

            meta = dcm.metadata or {}
            # Mirror some widths/heights to what the panel expects
            if getattr(ds, "Columns", None):
                meta.setdefault("ImageWidth", str(ds.Columns))
            if getattr(ds, "Rows", None):
                meta.setdefault("ImageHeight", str(ds.Rows))
            return _norm8(arr), meta

        # TIFF
        if suffix in (".tif", ".tiff"):
            tr = TIFFReader(str(path))
            arr = tr.get_array()
            meta = tr.get_metadata() or {}
            return _norm8(arr), meta

        # Fallback: treat as regular image
        img = Image.open(str(path)).convert("RGB")
        return np.array(img), {"SourceFile": path.name}

    # ---------- export (per-image JSON) --------------------------------------


    def _set_initial_split_sizes(self) -> None:
        """Give most space to the viewer on first paint."""
        try:
            total = max(self.width(), 1200)
            left = 240   # file list
            right = 360  # metadata
            center = max(600, total - (left + right + 40))
            self.splitter.setSizes([left, center, right])
        except Exception:
            pass


    def _choose_out_dir(self) -> Optional[Path]:
        out = QFileDialog.getExistingDirectory(self, "Choose Export Folder")
        if not out:
            return None
        out_dir = Path(out)
        (out_dir / "images").mkdir(parents=True, exist_ok=True)
        return out_dir

    def _export_current(self) -> None:
        if not self._paths:
            QMessageBox.information(self, "Export", "No file loaded.")
            return
        out_dir = self._choose_out_dir()
        if not out_dir:
            return

        idx = self.list_widget.currentRow()
        idx = idx if idx >= 0 else 0
        path = self._paths[idx]

        try:
            arr, meta = self._read_pixels_and_metadata(path)
            self._export_one(out_dir, arr, meta, seq_num=idx + 1)
            QMessageBox.information(self, "Export", "Exported current image.")
        except Exception as e:
            log.exception("Export failed")
            QMessageBox.critical(self, "Export", f"Export failed: {e}")

    def _bulk_export(self) -> None:
        if not self._paths:
            QMessageBox.information(self, "Bulk Export", "No files loaded.")
            return
        out_dir = self._choose_out_dir()
        if not out_dir:
            return

        ok = 0
        for i, p in enumerate(self._paths, start=1):
            try:
                arr, meta = self._read_pixels_and_metadata(p)
                self._export_one(out_dir, arr, meta, seq_num=i)
                ok += 1
            except Exception as e:
                log.warning("Skipping %s due to error: %s", p.name, e)

        QMessageBox.information(self, "Bulk Export", f"Exported {ok} / {len(self._paths)} images.")

    def _export_one(self, out_dir: Path, arr: np.ndarray, meta: Dict[str, Any], seq_num: int) -> None:
        """
        Save a TIFF + JSON sidecar per image without overwriting prior exports.
        File stem preference: SOPInstanceUID -> picture_uid -> 0001/0002/...
        """
        images_dir = out_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        # Choose stem
        candidate = str(meta.get("SOPInstanceUID") or meta.get("picture_uid") or f"{seq_num:04d}")
        stem = _sanitize_stem(candidate)
        if not stem:
            stem = f"{seq_num:04d}"

        tiff_path = _unique_path(images_dir, stem, ".tiff")
        json_path = tiff_path.with_suffix(".json")

        # Debug prints so you can see what happened
        print(f"[export] base stem chosen: {candidate} -> sanitized: {stem}")
        print(f"[export] writing image: {tiff_path}")
        print(f"[export] writing sidecar: {json_path}")

        # Save TIFF (RGB or L), data as uint8
        arr8 = _norm8(arr)
        if arr8.ndim == 2:
            im = Image.fromarray(arr8, mode="L")
        elif arr8.ndim == 3 and arr8.shape[2] == 3:
            im = Image.fromarray(arr8, mode="RGB")
        else:
            raise ValueError(f"Unsupported array shape for export: {arr8.shape}")
        im.save(str(tiff_path), format="TIFF")

        # Compose sidecar JSON
        meta_out = dict(meta) if meta else {}
        meta_out.setdefault("SOPInstanceUID", meta.get("SOPInstanceUID", ""))
        # Keep a stable picture_uid for TIFFs to re-associate later
        meta_out["picture_uid"] = stem
        meta_out["SourceFile"] = tiff_path.name
        # width/height sanity
        h, w = (arr8.shape[0], arr8.shape[1]) if arr8.ndim >= 2 else (None, None)
        if w and h:
            meta_out.setdefault("ImageWidth", str(w))
            meta_out.setdefault("ImageHeight", str(h))

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(meta_out, f, ensure_ascii=False, indent=2)

        log.info("Exported %s and %s", tiff_path.name, json_path.name)
