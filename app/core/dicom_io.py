# app/core/dicom_io.py
from __future__ import annotations
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import date, datetime

import numpy as np
import pydicom
from pydicom.uid import ImplicitVRLittleEndian

log = logging.getLogger(__name__)

# ---- initialization ----------------------------------------------------------

_INITIALIZED = False


def initialize_dicom_environment():
    """Warm up pixel handlers so first read is reliable."""
    global _INITIALIZED
    if _INITIALIZED:
        return
    try:
        import pydicom.config
        from pydicom.pixel_data_handlers import numpy_handler, pillow_handler
        handlers = [numpy_handler, pillow_handler]
        try:
            from pydicom.pixel_data_handlers import pylibjpeg_handler
            handlers.insert(0, pylibjpeg_handler)
        except Exception:
            pass
        pydicom.config.pixel_data_handlers = handlers
        pydicom.config.enforce_valid_values = False
        pydicom.config.convert_wrong_length_to_UN = True

        # tiny warm-up dataset
        from pydicom.dataset import Dataset, FileMetaDataset
        ds = Dataset()
        ds.file_meta = FileMetaDataset()
        ds.file_meta.TransferSyntaxUID = ImplicitVRLittleEndian
        ds.is_little_endian = True
        ds.is_implicit_VR = True
        ds.Rows = 1
        ds.Columns = 1
        ds.BitsAllocated = 8
        ds.SamplesPerPixel = 1
        ds.PixelRepresentation = 0
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.PixelData = b"\x00"
        _ = ds.pixel_array
    except Exception:
        pass
    _INITIALIZED = True
    log.info("DICOM environment initialized (handlers configured, warm-up done)")

# ---- helper utilities --------------------------------------------------------


def _parse_da(val: Any) -> Optional[date]:
    """
    Parse a DICOM DA (YYYYMMDD) or a relaxed 'YYYY-MM-DD' into datetime.date.
    If parsing fails, return None.
    """
    if not val:
        return None
    s = str(val).strip()
    if len(s) == 8 and s.isdigit():
        # YYYYMMDD
        try:
            return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
        except Exception:
            return None
    # Try relaxed 'YYYY-MM-DD'
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _format_as_years(n_years: int) -> str:
    """
    Format integer years as DICOM AS (Age String) per VR=AS: nnnY.
    (e.g., 7 -> "007Y", 63 -> "063Y")
    """
    if n_years < 0:
        n_years = 0
    if n_years > 999:
        n_years = 999
    return f"{n_years:03d}Y"


def _compute_age_from_dates(birth: Optional[date], ref: Optional[date]) -> Optional[str]:
    """
    Compute age in whole years at 'ref' date, return DICOM AS like '063Y'.
    If either date missing, return None.
    """
    if not birth or not ref:
        return None
    # Whole years difference
    years = ref.year - birth.year - ((ref.month, ref.day) < (birth.month, birth.day))
    return _format_as_years(years)


# ---- DicomFile ---------------------------------------------------------------

# Minimal set + diagnosis & clinical fields
TAGS = {
    "PatientName": (0x0010, 0x0010),
    "PatientID": (0x0010, 0x0020),
    "PatientBirthDate": (0x0010, 0x0030),
    "PatientSex": (0x0010, 0x0040),
    "PatientAge": (0x0010, 0x1010),  # VR=AS (e.g., "063Y")
    "StudyDate": (0x0008, 0x0020),
    "StudyTime": (0x0008, 0x0030),
    "StudyDescription": (0x0008, 0x1030),
    "SeriesDescription": (0x0008, 0x103E),
    "Modality": (0x0008, 0x0060),
    "Manufacturer": (0x0008, 0x0070),
    "ModelName": (0x0008, 0x1090),
    "SoftwareVersions": (0x0018, 0x1020),
    "Laterality": (0x0020, 0x0062),
    "BodyPartExamined": (0x0018, 0x0015),
    "SOPInstanceUID": (0x0008, 0x0018),
    "ImageWidth": (0x0028, 0x0011),   # Columns
    "ImageHeight": (0x0028, 0x0010),  # Rows
    # Diagnosis/notes (simple tags)
    "AdmittingDiagnosesDescription": (0x0008, 0x1080),
    "AdditionalPatientHistory": (0x0010, 0x21B0),
    "StudyComments": (0x0032, 0x4000),
    # AcquisitionDate for age derivation
    "AcquisitionDate": (0x0008, 0x0022),
}

# Sequences we parse specially
REQUEST_ATTRIBUTES_SEQ = (0x0040, 0x0275)           # RequestAttributesSequence
REASON_FOR_REQUESTED_PROCEDURE = (0x0040, 0x1002)   # inside RequestAttributesSequence
ADMITTING_DIAGNOSES_CODE_SEQ = (0x0008, 0x1084)     # at root


class DicomFile:
    def __init__(self, file_path: str):
        initialize_dicom_environment()
        self.path = Path(file_path)
        self.dataset: Optional[pydicom.Dataset] = None
        self.metadata: Dict[str, Any] = {}
        self._pixel: Optional[np.ndarray] = None
        self._read_header()
        self._extract_metadata()

    # -- reading ---------------------------------------------------------------
    def _read_header(self):
        self.dataset = pydicom.dcmread(
            str(self.path), stop_before_pixels=True, force=True, defer_size=4096
        )
        # Ensure Transfer Syntax present for later pixel read
        if not getattr(self.dataset.file_meta, "TransferSyntaxUID", None):
            self.dataset.file_meta.TransferSyntaxUID = ImplicitVRLittleEndian

    def get_pixel_array(self) -> np.ndarray:
        if self._pixel is not None:
            return self._pixel
        ds = pydicom.dcmread(str(self.path), force=True)  # full
        if not getattr(ds.file_meta, "TransferSyntaxUID", None):
            ds.file_meta.TransferSyntaxUID = ImplicitVRLittleEndian
        self.dataset = ds
        self._pixel = ds.pixel_array
        return self._pixel

    # -- metadata --------------------------------------------------------------
    def _get(self, tag):
        ds = self.dataset
        if ds is None:
            return None
        if tag in ds and ds[tag].value not in ("", None):
            v = ds[tag].value
            try:
                return v.original_string  # type: ignore
            except Exception:
                return v
        return None

    def _extract_metadata(self):
        m: Dict[str, Any] = {}
        # Simple tags
        for name, tag in TAGS.items():
            val = self._get(tag)
            if val is None:
                continue
            txt = str(val)
            if name in ("StudyDate", "PatientBirthDate", "AcquisitionDate") and len(txt) == 8 and txt.isdigit():
                txt = f"{txt[:4]}-{txt[4:6]}-{txt[6:]}"
            if name in ("StudyTime",) and len(txt) >= 6 and txt[:6].isdigit():
                txt = f"{txt[:2]}:{txt[2:4]}:{txt[4:6]}"
            m[name] = txt

        # Diagnosis codes (sequence)
        codes = []
        try:
            if ADMITTING_DIAGNOSES_CODE_SEQ in self.dataset:
                seq = self.dataset[ADMITTING_DIAGNOSES_CODE_SEQ].value or []
                for item in seq:
                    code = []
                    if hasattr(item, "CodeValue"):
                        code.append(str(item.CodeValue))
                    if hasattr(item, "CodingSchemeDesignator"):
                        code.append(str(item.CodingSchemeDesignator))
                    if hasattr(item, "CodeMeaning"):
                        code.append(str(item.CodeMeaning))
                    if code:
                        codes.append(" | ".join(code))
        except Exception:
            pass
        if codes:
            m["DiagnosisCodes"] = codes

        # Reason for requested procedure (RequestAttributesSequence → 0040,1002)
        try:
            if REQUEST_ATTRIBUTES_SEQ in self.dataset:
                seq = self.dataset[REQUEST_ATTRIBUTES_SEQ].value or []
                for item in seq:
                    if REASON_FOR_REQUESTED_PROCEDURE in item:
                        val = item[REASON_FOR_REQUESTED_PROCEDURE].value
                        if val:
                            m["ReasonForRequestedProcedure"] = str(val)
                            break
        except Exception:
            pass

        # Derived / UI synonyms
        if m.get("AdmittingDiagnosesDescription"):
            m["Diagnosis"] = m["AdmittingDiagnosesDescription"]

        # Notes aggregation
        notes = []
        if m.get("AdditionalPatientHistory"):
            notes.append(str(m["AdditionalPatientHistory"]))
        if m.get("StudyComments"):
            notes.append(str(m["StudyComments"]))
        if notes:
            m["ClinicalNotes"] = "\n".join(notes)

        # Dimensions sanity
        if m.get("ImageWidth") and m.get("ImageHeight"):
            try:
                m["ImageWidth"] = int(m["ImageWidth"])
                m["ImageHeight"] = int(m["ImageHeight"])
            except Exception:
                pass

        # --- PatientAge: use tag if present, else derive from dates ------------
        if not m.get("PatientAge"):
            birth = _parse_da(m.get("PatientBirthDate"))
            # Prefer StudyDate, then AcquisitionDate, then (last resort) today
            ref = _parse_da(m.get("StudyDate")) or _parse_da(m.get("AcquisitionDate")) or date.today()
            derived = _compute_age_from_dates(birth, ref) if birth else None
            if derived:
                m["PatientAge"] = derived
                try:
                    # also expose numeric years if helpful downstream
                    m["PatientAgeYears"] = int(derived[:3])
                except Exception:
                    pass

        self.metadata = m
