"""
Robust export pipeline (DICOM/regular images) with a backward-compatible config.

- ExportConfig now has a default out_dir (~/FundusReaderWriter-Exports)
- Back-compat alias: config.export_dir (getter + setter)
- Exporter.create_layout() creates images/ and metadata/ and metadata.jsonl (optional)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Protocol, runtime_checkable
import logging

logger = logging.getLogger(__name__)

# orjson is optional; fall back to stdlib json
try:
    import orjson
    def _dumps_line(obj: Dict[str, Any]) -> bytes:
        return orjson.dumps(obj) + b"\n"
except Exception:
    import json
    def _dumps_line(obj: Dict[str, Any]) -> bytes:
        return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


# --- Protocols for duck-typing (works with your DicomFile and RegularImage) ---

@runtime_checkable
class _Exportable(Protocol):
    file_path: Path
    picture_uid: Optional[str]
    metadata: Dict[str, Any]

    def export_image(self, output_path: Path, format: str = "TIFF") -> Path: ...
    def get_metadata_for_export(self, deidentify: bool = False) -> Dict[str, Any]: ...


@dataclass
class ExportConfig:
    # NEW: give out_dir a safe default so UI can call ExportConfig() with no args
    out_dir: Path = field(default_factory=lambda: Path.home() / "FundusReaderWriter-Exports")

    # Layout
    images_subdir: str = "images"
    metadata_subdir: str = "metadata"

    # Options
    image_format: str = "TIFF"
    overwrite: bool = True
    include_phi: bool = True
    write_sidecar_json: bool = True
    combine_metadata_jsonl: bool = True

    # --- Back-compat alias used by the UI (getter + setter) ---
    @property
    def export_dir(self) -> Path:
        """Legacy alias so older UI code that reads `config.export_dir` keeps working."""
        return self.out_dir

    @export_dir.setter
    def export_dir(self, value: Path) -> None:
        """Allow the UI to assign a Path (or str) to `config.export_dir`."""
        self.out_dir = Path(value)

    # Helpers
    def images_dir(self) -> Path:
        return self.out_dir / self.images_subdir

    def metadata_dir(self) -> Path:
        return self.out_dir / self.metadata_subdir

    def jsonl_path(self) -> Path:
        return self.out_dir / "metadata.jsonl"

    def ensure_dirs(self) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir().mkdir(parents=True, exist_ok=True)
        self.metadata_dir().mkdir(parents=True, exist_ok=True)


class Exporter:
    def __init__(self, config: ExportConfig):
        self.config = config

    # Public API ---------------------------------------------------------------

    def export_bulk(self, items: Iterable[_Exportable]) -> int:
        """
        Export many items (DicomFile or RegularImage). Returns count exported.
        """
        cfg = self.config
        cfg.ensure_dirs()
        logger.info(f"Export directories created at {cfg.out_dir}")

        # Prepare JSONL stream (optional)
        jsonl_fh = None
        if cfg.combine_metadata_jsonl:
            jsonl_path = cfg.jsonl_path()
            if jsonl_path.exists() and cfg.overwrite:
                try:
                    jsonl_path.unlink()
                except Exception:
                    pass
            jsonl_fh = open(jsonl_path, "ab")

        exported = 0
        try:
            for item in items:
                try:
                    img_path, sidecar = self._export_single(item)
                    exported += 1
                    logger.info(f"Successfully exported image to {img_path}")
                    if sidecar:
                        logger.debug(f"Wrote sidecar {sidecar}")

                    if jsonl_fh:
                        md = self._prepare_metadata(item)
                        jsonl_fh.write(_dumps_line(md))
                except Exception as e:
                    logger.warning(f"Failed to export {getattr(item, 'file_path', 'item')}: {e}")
                    continue
        finally:
            if jsonl_fh:
                jsonl_fh.close()
                logger.info(f"Exported combined metadata to {self.config.jsonl_path()}")

        return exported

    def export_one(self, item: _Exportable) -> Tuple[Path, Optional[Path]]:
        """Export a single item and return (image_path, sidecar_json_path|None)."""
        self.config.ensure_dirs()
        return self._export_single(item)

    # Internals ----------------------------------------------------------------

    def _export_single(self, item: _Exportable) -> Tuple[Path, Optional[Path]]:
        cfg = self.config

        # Choose a stable file stem: prefer the item's picture_uid, else use stem
        stem = getattr(item, "picture_uid", None) or Path(getattr(item, "file_path")).stem

        # Image path
        ext = (cfg.image_format or "TIFF").upper()
        if ext == "TIFF":
            suffix = ".tiff"
        else:
            suffix = "." + ext.lower()
        img_path = cfg.images_dir() / f"{stem}{suffix}"

        # Overwrite policy
        if img_path.exists() and not cfg.overwrite:
            raise RuntimeError(f"Refusing to overwrite existing file: {img_path}")

        # Do the export (duck-typed)
        item.export_image(img_path, format=cfg.image_format)

        # Sidecar JSON (optional)
        sidecar_path: Optional[Path] = None
        if cfg.write_sidecar_json:
            sidecar_path = cfg.metadata_dir() / f"{stem}.json"
            md = self._prepare_metadata(item)
            sidecar_path.write_bytes(_dumps_line(md).rstrip(b"\n"))

        return img_path, sidecar_path

    def _prepare_metadata(self, item: _Exportable) -> Dict[str, Any]:
        md = item.get_metadata_for_export(deidentify=not self.config.include_phi)
        # Ensure some common fields exist
        md.setdefault("export_image", (self.config.images_dir() / f"{(getattr(item, 'picture_uid', None) or Path(item.file_path).stem)}.tiff").name)
        if getattr(item, "picture_uid", None):
            md.setdefault("picture_uid", item.picture_uid)
        return md
