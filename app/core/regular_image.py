"""
Regular (non-DICOM) image reader with TIFF-first metadata pipeline,
sidecar JSON support, and display-field normalization.

Back-compat alias exposed at bottom:
    RegularImageFile = RegularImage
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
import logging
import hashlib
import json
from datetime import datetime

import numpy as np
from PIL import Image, ExifTags

# Optional helpers (used defensively)
try:
    import tifffile  # type: ignore
    _HAS_TIFFFILE = True
except Exception:
    _HAS_TIFFFILE = False

try:
    import orjson  # type: ignore
    _HAS_ORJSON = True
except Exception:
    _HAS_ORJSON = False

logger = logging.getLogger(__name__)


def _sha256_uid(file_path: Path) -> str:
    """Return a DICOM-like UID (2.25.<hex>) from SHA-256 of the file."""
    h = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    # Use first 38 hex chars (152 bits) => fits under 2.25.<digits> length limits yet stable
    return f"2.25.{h.hexdigest()[:38]}"


def _norm_date(v: str) -> str:
    """Best-effort normalize to YYYYMMDD (accepts 'YYYY-MM-DD' or already compact)."""
    if not v:
        return ""
    s = str(v).strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s.replace("-", "")
    return s


def _norm_time(v: str) -> str:
    """Best-effort normalize to HHMMSS (accepts 'HH:MM:SS' or already compact)."""
    if not v:
        return ""
    s = str(v).strip()
    if ":" in s and len(s) >= 8:
        return s[0:2] + s[3:5] + s[6:8]
    return s


def _calc_age_YYYYMMDD(birth: str, study: str) -> Optional[str]:
    """Return DICOM age like '065Y' if both dates present."""
    try:
        b = datetime.strptime(_norm_date(birth), "%Y%m%d")
        s = datetime.strptime(_norm_date(study), "%Y%m%d")
        years = s.year - b.year - ((s.month, s.day) < (b.month, b.day))
        years = max(0, years)
        return f"{years:03d}Y"
    except Exception:
        return None


class RegularImage:
    """Wrapper for regular images providing a DICOM-like interface and metadata dict."""

    def __init__(self, file_path: str | Path):
        self.file_path = Path(file_path)
        if not self.file_path.exists():
            raise FileNotFoundError(str(self.file_path))

        self.image: Optional[Image.Image] = None
        self.pixel_array: Optional[np.ndarray] = None
        self.metadata: Dict[str, Any] = {}        # raw-ish, merged
        self._display_meta: Dict[str, Any] = {}   # normalized for the UI panel
        self.picture_uid: Optional[str] = None

        self._load_image()
        self._extract_metadata()   # fills self.metadata and self._display_meta

    # ---------- image loading ----------

    def _load_image(self) -> None:
        img = Image.open(self.file_path)
        # Convert to a common mode; keep RGB if present
        if img.mode not in ("L", "RGB", "RGBA"):
            img = img.convert("RGB")
        self.image = img
        self.pixel_array = np.array(img)
        logger.info(f"Loaded image: {self.file_path.name} ({self.image.size})")

    def get_pixel_array(self) -> np.ndarray:
        return self.pixel_array if self.pixel_array is not None else np.array(self.image)

    def get_image(self) -> Image.Image:
        return self.image

    # ---------- metadata pipeline ----------

    def _extract_metadata(self) -> None:
        """Two-stage:
        1) Read native tags (tifffile for TIFF, PIL/EXIF for others)
        2) Merge sidecar JSON if present
        3) Normalize keys -> display fields expected by MetadataPanel
        """
        raw: Dict[str, Any] = {}

        if self.file_path.suffix.lower() in (".tif", ".tiff"):
            raw.update(self._tiff_core())
        else:
            raw.update(self._std_core())

        # Sidecar JSON merge (if exists)
        side = self._load_sidecar(self.file_path)
        if side:
            # only overlay non-empty values
            for k, v in side.items():
                if v not in (None, "", [], {}):
                    raw[k] = v

        # Ensure dimensions
        if self.image:
            raw.setdefault("ImageWidth", self.image.width)
            raw.setdefault("ImageHeight", self.image.height)

        # Ensure SOP-like UID for non-DICOM
        sop = _sha256_uid(self.file_path)
        raw.setdefault("SOPInstanceUID", sop)
        self.picture_uid = sop

        self.metadata = raw
        self._display_meta = self._to_display_fields(raw)

        # Friendly log for what the panel should see
        keys_to_log = [
            "PatientName", "PatientID", "PatientBirthDate",
            "StudyDate", "StudyTime",
            "StudyDescription", "SeriesDescription",
            "Manufacturer", "ManufacturerModel", "ModelName",
            "Laterality", "SOPInstanceUID",
            "Diagnosis", "ClinicalNotes", "ReasonForRequestedProcedure", "StudyComments"
        ]
        logger.info(f"[META] Final display fields for {self.file_path.name}:")
        for k in keys_to_log:
            if k in self._display_meta:
                logger.info(f"    {k:24s} {self._display_meta[k]}")

    # ---- core readers ----

    def _tiff_core(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        # tifffile: robust for scientific/OME/ImageJ TIFFs
        if _HAS_TIFFFILE:
            try:
                with tifffile.TiffFile(str(self.file_path)) as tf:
                    t0 = tf.pages[0] if tf.pages else None
                    if t0 is not None:
                        tags = {tag.name: tag.value for tag in t0.tags.values() if hasattr(tag, "name")}
                        # Common TIFF tag names -> store raw
                        for k, v in tags.items():
                            out[k] = v
                    # OME/XML if present
                    if "ImageDescription" in out and isinstance(out["ImageDescription"], (bytes, str)):
                        # keep as-is; panel mapping will handle
                        pass
                    # Resolution mapping if present
                    xres = out.get("XResolution")
                    yres = out.get("YResolution")
                    if isinstance(xres, tuple) and len(xres) == 2 and isinstance(yres, tuple) and len(yres) == 2:
                        try:
                            out["PixelSpacing"] = f"{xres[0]}/{xres[1]}\\{yres[0]}/{yres[1]}"
                        except Exception:
                            pass
            except Exception as e:
                logger.debug(f"tifffile parse failed: {e}")

        # Try EXIF via PIL as well (some TIFFs carry EXIF blocks)
        try:
            if hasattr(self.image, "_getexif") and self.image._getexif():
                exif = {}
                for tag, val in self.image._getexif().items():
                    name = ExifTags.TAGS.get(tag, f"Unknown_{tag}")
                    # decode bytes conservatively
                    if isinstance(val, bytes):
                        try:
                            val = val.decode("utf-8", "replace")
                        except Exception:
                            val = str(val)
                    exif[name] = val
                out.update(exif)
        except Exception as e:
            logger.debug(f"EXIF read failed: {e}")

        return out

    def _std_core(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "FileName": self.file_path.name,
            "MIMEType": f"image/{self.file_path.suffix[1:].lower()}",
        }
        try:
            if hasattr(self.image, "_getexif") and self.image._getexif():
                exif = {}
                for tag, val in self.image._getexif().items():
                    name = ExifTags.TAGS.get(tag, f"Unknown_{tag}")
                    if isinstance(val, bytes):
                        try:
                            val = val.decode("utf-8", "replace")
                        except Exception:
                            val = str(val)
                    exif[name] = val
                out.update(exif)
        except Exception as e:
            logger.debug(f"Standard EXIF read failed: {e}")
        return out

    # ---- sidecar support ----

    def _load_sidecar(self, img_path: Path) -> Dict[str, Any]:
        """Look for a per-image JSON sidecar produced by your exporter.

        Searched locations (in order):
          - <img_dir>/<basename>.json
          - <project_root>/metadata/<basename>.json     (covers your exporter layout)
          - <img_dir>/../metadata/<basename>.json
        """
        base = img_path.stem  # without suffix
        candidates: List[Path] = []

        # image folder
        candidates.append(img_path.with_suffix(".json"))

        # project-root / metadata (if user picked test/teset dir layout)
        # project root assumed as repo root (two up at most)
        repo_root = self._guess_repo_root(img_path)
        if repo_root:
            candidates.append(repo_root / "metadata" / f"{base}.json")

        # sibling metadata folder
        candidates.append(img_path.parent.parent / "metadata" / f"{base}.json")

        logger.info(f"[SIDE] Searching sidecars for {img_path.name}")
        logger.info("[SIDE] Candidate directories (in order):")
        for p in [img_path.parent, repo_root or img_path.parent, (repo_root / 'metadata') if repo_root else img_path.parent]:
            logger.info(f"       - {p}")

        for cand in candidates:
            if cand.exists():
                try:
                    data = self._read_json(cand)
                    # Normalize a couple of time/date fields if marked like "15:12:58"
                    if "StudyTime" in data:
                        data["StudyTime"] = _norm_time(str(data["StudyTime"]))
                    if "AcquisitionTime" in data:
                        data["AcquisitionTime"] = _norm_time(str(data["AcquisitionTime"]))
                    if "StudyDate" in data:
                        data["StudyDate"] = _norm_date(str(data["StudyDate"]))
                    if "PatientBirthDate" in data:
                        data["PatientBirthDate"] = _norm_date(str(data["PatientBirthDate"]))
                    logger.info(f"[SIDE] Loaded per-image JSON: {cand}")
                    # small preview
                    preview = {k: data.get(k) for k in (
                        "PatientName", "PatientID", "PatientBirthDate",
                        "StudyDate", "StudyTime", "Manufacturer",
                        "ManufacturerModel", "Laterality", "SOPInstanceUID"
                    ) if k in data}
                    logger.info(f"[SIDE] Sidecar values preview: {preview}")
                    return data
                except Exception as e:
                    logger.debug(f"Failed to read sidecar {cand}: {e}")
            else:
                # Verbose note for first directory only
                logger.info(f"[SIDE]   (missing) {cand}")
        return {}

    def _guess_repo_root(self, img_path: Path) -> Optional[Path]:
        # Heuristic: walk up a few parents and pick the first containing a 'metadata' dir
        for p in [img_path.parent, *img_path.parents]:
            if (p / "metadata").exists():
                return p
        # Also try the repo root (two up) if running from source tree
        two_up = img_path.parents[2] if len(img_path.parents) >= 3 else img_path.parent
        if (two_up / "metadata").exists():
            return two_up
        return None

    def _read_json(self, path: Path) -> Dict[str, Any]:
        if _HAS_ORJSON:
            return orjson.loads(path.read_bytes())
        return json.loads(path.read_text(encoding="utf-8"))

    # ---- normalization to panel fields ----

    def _to_display_fields(self, src: Dict[str, Any]) -> Dict[str, Any]:
        """Map mixed TIFF/EXIF/sidecar keys -> the exact keys the MetadataPanel shows."""
        # 1) Start with direct picks (sidecar already overlaid on top)
        out: Dict[str, Any] = {}
        direct_map = {
            # Patient
            "PatientName": "PatientName",
            "PatientID": "PatientID",
            "PatientBirthDate": "PatientBirthDate",
            "PatientSex": "PatientSex",

            # Study/Series
            "StudyDate": "StudyDate",
            "StudyTime": "StudyTime",
            "StudyDescription": "StudyDescription",
            "SeriesDescription": "SeriesDescription",
            "Modality": "Modality",

            # Device
            "Manufacturer": "Manufacturer",
            "ManufacturerModel": "ManufacturerModel",
            "ModelName": "ManufacturerModel",   # fallback
            "SoftwareVersions": "SoftwareVersions",

            # Image properties
            "ImageWidth": "ImageWidth",
            "ImageHeight": "ImageHeight",
            "SamplesPerPixel": "SamplesPerPixel",
            "BitsAllocated": "BitsAllocated",
            "PhotometricInterpretation": "PhotometricInterpretation",

            # Laterality / eye
            "Laterality": "Laterality",

            # Times (we'll normalize later)
            "AcquisitionDate": "AcquisitionDate",
            "AcquisitionTime": "AcquisitionTime",

            # Clinical/diagnosis-ish
            "Diagnosis": "Diagnosis",
            "AdditionalPatientHistory": "ClinicalNotes",
            "StudyComments": "StudyComments",
            "ReasonForRequestedProcedure": "ReasonForRequestedProcedure",

            # IDs
            "SOPInstanceUID": "SOPInstanceUID",
        }

        # Copy with gentle coercion to plain str/int/float for display
        for sk, dk in direct_map.items():
            if sk in src and src[sk] not in (None, "", [], {}):
                val = src[sk]
                # Avoid accidentally shoving an entire dict into a text field
                if isinstance(val, (dict, list)):
                    # don't promote unless it's one of the textareas we *want* as JSON
                    # here we prefer to skip; sidecar JSON occasionally appears in ImageDescription
                    continue
                out[dk] = val

        # 2) Extra hints from EXIF common tags -> DICOM-like
        if "Make" in src and "Manufacturer" not in out:
            out["Manufacturer"] = src["Make"]
        if "Model" in src and "ManufacturerModel" not in out:
            out["ManufacturerModel"] = src["Model"]
        if "ImageDescription" in src and "StudyDescription" not in out:
            # Most cameras put short text here; keep it if it's shortish
            v = src["ImageDescription"]
            if isinstance(v, (str, bytes)) and len(str(v)) <= 256:
                out["StudyDescription"] = str(v)

        # 3) Fallback defaults (only if empty)
        defaults = {
            "Modality": "OP",
            "BodyPartExamined": "EYE",
            "PatientSex": "U",
        }
        for k, v in defaults.items():
            out.setdefault(k, v)

        # 4) Normalize dates/times
        if "StudyDate" in out:
            out["StudyDate"] = _norm_date(str(out["StudyDate"]))
        if "AcquisitionDate" in out:
            out["AcquisitionDate"] = _norm_date(str(out["AcquisitionDate"]))
        if "PatientBirthDate" in out:
            out["PatientBirthDate"] = _norm_date(str(out["PatientBirthDate"]))

        if "StudyTime" in out:
            out["StudyTime"] = _norm_time(str(out["StudyTime"]))
        if "AcquisitionTime" in out:
            out["AcquisitionTime"] = _norm_time(str(out["AcquisitionTime"]))

        # 5) Compute PatientAge if possible
        age = _calc_age_YYYYMMDD(out.get("PatientBirthDate", ""), out.get("StudyDate", ""))
        if age and "PatientAge" not in out:
            out["PatientAge"] = age

        return out

    # ---------- API consumed by the MetadataPanel ----------

    def get_metadata_for_display(self) -> Dict[str, Any]:
        """MetadataPanel will call this if present. Keep keys exactly as panel expects."""
        return dict(self._display_meta)

    # (Kept for compatibility—panel also checks .metadata directly)
    # def metadata (already exists as dict)


# Back-compat alias so legacy imports keep working:
RegularImageFile = RegularImage
__all__ = ["RegularImage", "RegularImageFile"]
