# app/core/tiff_reader.py
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import date, datetime

from PIL import Image, TiffImagePlugin

log = logging.getLogger(__name__)

try:
    import tifffile  # optional, but helpful for some tags/XMP
    _HAS_TIFFFILE = True
except Exception:
    _HAS_TIFFFILE = False

try:
    # optional XMP parsing; safe if not installed
    from libxmp import XMPMeta, XMPFiles
    _HAS_XMP = True
except Exception:
    _HAS_XMP = False


DICOMISH_FIELDS = [
    "PatientName", "PatientID", "PatientBirthDate", "PatientAge", "PatientAgeYears", "PatientSex",
    "StudyDate", "StudyTime", "StudyDescription", "SeriesDescription",
    "Modality", "Manufacturer", "ManufacturerModel", "ModelName",
    "SoftwareVersions", "Laterality", "BodyPartExamined",
    "Diagnosis", "DiagnosisCodes", "ClinicalNotes",
    "ReasonForRequestedProcedure", "StudyComments",
    "SOPInstanceUID", "ImageWidth", "ImageHeight"
]

# --------- small helpers reused here -----------------------------------------

def _parse_da(val: Any) -> Optional[date]:
    """Parse DICOM-style 'YYYYMMDD' or relaxed 'YYYY-MM-DD' to date."""
    if not val:
        return None
    s = str(val).strip()
    if len(s) == 8 and s.isdigit():
        try:
            return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
        except Exception:
            return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _format_as_years(n_years: int) -> str:
    if n_years < 0:
        n_years = 0
    if n_years > 999:
        n_years = 999
    return f"{n_years:03d}Y"


def _compute_age_from_dates(birth: Optional[date], ref: Optional[date]) -> Optional[str]:
    if not birth or not ref:
        return None
    years = ref.year - birth.year - ((ref.month, ref.day) < (birth.month, birth.day))
    return _format_as_years(years)


class TIFFReader:
    """
    Loads a TIFF image and returns a numpy array + a DICOM-like metadata dict.

    Metadata precedence:
      1) embedded XMP (if present)
      2) TIFF/EXIF/TIFF-tag values
      3) per-image sidecar JSON in:
          - same folder as image
          - parent folder
          - <parent>/metadata/
      4) combined metadata.jsonl (if found), last resort

    Any found values are mapped into the right-hand panel's field names.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._img: Optional[Image.Image] = None
        self._arr = None
        self._meta: Dict[str, Any] = {}

    # ---------- public API ----------

    def get_array(self):
        if self._arr is not None:
            return self._arr
        self._img = Image.open(str(self.path))
        # Ensure RGB for display (keep grayscale as 'L')
        if self._img.mode not in ("RGB", "L"):
            try:
                self._img = self._img.convert("RGB")
            except Exception:
                pass
        import numpy as np
        self._arr = np.array(self._img)
        return self._arr

    def get_metadata(self) -> Dict[str, Any]:
        if self._meta:
            return self._meta

        merged: Dict[str, Any] = {}

        # 1) Embedded XMP (if any)
        xmp = self._read_xmp_packet()
        if xmp:
            log.info("[TIFF] XMP fields found: %s", list(xmp.keys())[:10])
            merged.update(xmp)

        # 2) TIFF/EXIF tags
        tag_meta = self._read_tiff_tags()
        if tag_meta:
            log.info("[TIFF] TIFF/EXIF tag fields found: %s", list(tag_meta.keys())[:10])
            merged.update(tag_meta)

        # 3) Sidecar JSON (per-image)
        sidecar = self._read_sidecar_json()
        if sidecar:
            log.info("[TIFF] Sidecar JSON fields found: %s", list(sidecar.keys())[:10])
            merged.update(sidecar)

        # 4) Combined JSONL file (match by picture uid or basename)
        jsonl = self._read_combined_jsonl()
        if jsonl:
            log.info("[TIFF] Combined JSONL fields found: %s", list(jsonl.keys())[:10])
            merged.update(jsonl)

        # Always include width/height fallback
        try:
            w, h = self._img.size if self._img else Image.open(str(self.path)).size
            merged.setdefault("ImageWidth", str(w))
            merged.setdefault("ImageHeight", str(h))
        except Exception:
            pass

        # Normalize / Map a few common aliases coming from tags/XMP
        self._meta = self._normalize(merged)

        # ---- PatientAge: prefer provided, else derive from birth + study/acq ---
        if not self._meta.get("PatientAge"):
            birth = _parse_da(self._meta.get("PatientBirthDate"))
            ref = _parse_da(self._meta.get("StudyDate")) or _parse_da(self._meta.get("AcquisitionDate")) or date.today()
            derived = _compute_age_from_dates(birth, ref) if birth else None
            if derived:
                self._meta["PatientAge"] = derived
                try:
                    self._meta["PatientAgeYears"] = int(derived[:3])
                except Exception:
                    pass

        log.info("[TIFF] Final mapped metadata keys: %s", [k for k in DICOMISH_FIELDS if k in self._meta])
        return self._meta

    # ---------- readers ----------

    def _read_tiff_tags(self) -> Dict[str, Any]:
        """
        Read common TIFF fields via Pillow (TIFF IFD) and optionally tifffile.
        """
        out: Dict[str, Any] = {}
        try:
            with Image.open(str(self.path)) as im:
                # Pillow: tag_v2 returns a dict-like, tag IDs are ints
                tags = getattr(im, "tag_v2", None)
                if tags:
                    # 270: ImageDescription (may contain JSON or free text)
                    desc = tags.get(270)
                    if desc:
                        text = self._decode_if_bytes(desc)
                        # If looks like JSON, merge it
                        if self._looks_like_json(text):
                            try:
                                out.update(json.loads(text))
                            except Exception:
                                out["ImageDescription"] = text
                        else:
                            out["StudyDescription"] = text  # alias to our field

                    # 271: Make, 272: Model, 305: Software, 306: DateTime
                    make = tags.get(271)
                    model = tags.get(272)
                    soft = tags.get(305)
                    dt   = tags.get(306)

                    if make:
                        out["Manufacturer"] = self._decode_if_bytes(make)
                    if model:
                        model_text = self._decode_if_bytes(model)
                        out["ManufacturerModel"] = model_text
                        out["ModelName"] = model_text
                    if soft:
                        out["SoftwareVersions"] = self._decode_if_bytes(soft)
                    if dt:
                        dt_text = self._decode_if_bytes(dt)
                        out.setdefault("StudyDate", self._date_from_datetime(dt_text))
                        out.setdefault("StudyTime", self._time_from_datetime(dt_text))
        except Exception as e:
            log.debug("Pillow TIFF tag read failed: %s", e, exc_info=True)

        # tifffile pass (optional): sometimes holds XMP or richer tag decoding
        if _HAS_TIFFFILE:
            try:
                with tifffile.TiffFile(str(self.path)) as tf:
                    page = tf.pages[0]
                    # XMP (if tifffile extracted it)
                    xmp = getattr(page, "xmp", None)
                    if xmp and isinstance(xmp, dict):
                        out.update(xmp)

                    # fallback for width/height
                    out.setdefault("ImageWidth", str(getattr(page, "imagewidth", "")))
                    out.setdefault("ImageHeight", str(getattr(page, "imagelength", "")))
            except Exception as e:
                log.debug("tifffile read failed: %s", e, exc_info=True)

        return out

    def _read_xmp_packet(self) -> Dict[str, Any]:
        """
        Try to extract XMP metadata.
        We first check tifffile.Page.xmp (handled above). If not,
        try libxmp to parse the file’s packet directly.
        """
        out: Dict[str, Any] = {}
        if _HAS_XMP:
            try:
                xmpfile = XMPFiles(file_path=str(self.path))
                xmp = xmpfile.get_xmp()
                if xmp:
                    # Example mappings; keys depend on the schema used by the exporter
                    def _get(ns, prop):
                        try:
                            return xmp.get_property(ns, prop)
                        except Exception:
                            return None

                    # Often custom namespaces; we keep it generic:
                    from libxmp import consts as XMPConst
                    pn = _get(XMPConst.NS_PHOTOSHOP, "Credit") or _get(XMPConst.NS_DC, "creator")
                    if pn:
                        out["PatientName"] = str(pn)

                    desc = _get(XMPConst.NS_DC, "description")
                    if desc and isinstance(desc, (list, tuple)):
                        out["StudyDescription"] = str(desc[0])

                xmpfile.close_file()
            except Exception as e:
                log.debug("XMP parse failed: %s", e, exc_info=True)
        return out

    def _read_sidecar_json(self) -> Dict[str, Any]:
        """
        Look for <basename>.json in likely places.
        """
        base = self.path.stem  # strips .tif/.tiff
        candidates = [
            self.path.parent / f"{base}.json",
            self.path.parent.parent / f"{base}.json",
            self.path.parent / "metadata" / f"{base}.json",
            self.path.parent.parent / "metadata" / f"{base}.json",
        ]
        for p in candidates:
            log.info("[TIFF] Checking sidecar: %s", p)
            if p.exists():
                try:
                    return json.loads(p.read_text())
                except Exception as e:
                    log.warning("Failed to parse sidecar %s: %s", p, e)
        return {}

    def _read_combined_jsonl(self) -> Dict[str, Any]:
        """
        Read metadata.jsonl (if present) and try to match this picture
        by either 'picture_uid' (set to the TIFF basename in your exports)
        or by SOPInstanceUID.
        """
        names = ["metadata.jsonl", "metadata/metadata.jsonl"]
        folders = [self.path.parent, self.path.parent.parent]
        picture_uid = self.path.stem

        for folder in folders:
            for name in names:
                p = folder / name
                if p.exists():
                    log.info("[TIFF] Scanning combined JSONL: %s", p)
                    try:
                        for line in p.read_text().splitlines():
                            if not line.strip():
                                continue
                            rec = json.loads(line)
                            if str(rec.get("picture_uid", "")).endswith(picture_uid) or \
                               rec.get("picture_uid") == picture_uid or \
                               rec.get("SourceFile", "") == self.path.name:
                                return rec
                    except Exception as e:
                        log.warning("Failed reading JSONL %s: %s", p, e)
        return {}

    # ---------- helpers ----------

    @staticmethod
    def _decode_if_bytes(v):
        if isinstance(v, (bytes, bytearray)):
            try:
                return v.decode("utf-8", "ignore")
            except Exception:
                return str(v)
        return v

    @staticmethod
    def _looks_like_json(s: Any) -> bool:
        if not isinstance(s, str):
            return False
        t = s.strip()
        return (t.startswith("{") and t.endswith("}")) or (t.startswith("[") and t.endswith("]"))

    @staticmethod
    def _date_from_datetime(dt: str) -> str:
        # "YYYY:MM:DD HH:MM:SS" -> "YYYY-MM-DD"
        try:
            parts = dt.split()
            y, m, d = parts[0].split(":")
            return f"{y}-{m}-{d}"
        except Exception:
            return dt

    @staticmethod
    def _time_from_datetime(dt: str) -> str:
        try:
            parts = dt.split()
            if len(parts) > 1:
                return parts[1].replace("-", ":")
            return ""
        except Exception:
            return ""

    def _normalize(self, meta: Dict[str, Any]) -> Dict[str, Any]:
        """
        Map various potential input keys into the panel’s DICOM-like names.
        """
        out: Dict[str, Any] = {}

        # Pass-through anything already named as expected
        for k in DICOMISH_FIELDS:
            if k in meta and meta[k] not in (None, ""):
                out[k] = meta[k]

        # Common aliases coming from exports / tags:
        alias_map = {
            "Model": "ManufacturerModel",
            "ModelName": "ManufacturerModel",
            "Make": "Manufacturer",
            "ImageDescription": "StudyDescription",
            "Software": "SoftwareVersions",
            "BodyPart": "BodyPartExamined",
            "Laterality": "Laterality",
            "Date": "StudyDate",
        }
        for a, b in alias_map.items():
            if a in meta and b not in out and meta[a]:
                out[b] = meta[a]

        # If StudyDate/PatientBirthDate came as "YYYYMMDD", fix display
        def _fix_date8(v):
            if isinstance(v, str) and len(v) == 8 and v.isdigit():
                return f"{v[:4]}-{v[4:6]}-{v[6:8]}"
            return v

        for key in ("StudyDate", "PatientBirthDate", "AcquisitionDate"):
            if key in meta and key not in out:
                out[key] = _fix_date8(meta[key])

        # If StudyTime came as "HHMMSS", fix display
        def _fix_time6(v):
            if isinstance(v, str) and len(v) >= 6 and v[:6].isdigit():
                return f"{v[:2]}:{v[2:4]}:{v[4:6]}"
            return v

        for key in ("StudyTime", "AcquisitionTime"):
            if key in meta and key not in out:
                out[key] = _fix_time6(meta[key])

        # Width/Height if present under other names
        for cand, target in (("ImageWidth", "ImageWidth"), ("ImageLength", "ImageHeight"),
                             ("Width", "ImageWidth"), ("Height", "ImageHeight")):
            if cand in meta and target not in out:
                out[target] = str(meta[cand])

        # Always include source file
        out.setdefault("SourceFile", self.path.name)

        return out
