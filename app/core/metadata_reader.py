from __future__ import annotations
"""
Unifies metadata coming from DICOM and TIFF so the UI always sees the same keys.
Also maps diagnosis/notes into UI names used by MetadataPanel.
"""

from typing import Dict, Any
from pathlib import Path
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class MetadataReader:
    # Keys the UI expects
    UI_KEYS = {
        "PatientName", "PatientID", "PatientBirthDate", "PatientSex", "PatientAge",
        "StudyDate", "StudyTime", "StudyDescription", "SeriesDescription", "Modality",
        "Manufacturer", "ManufacturerModel", "ModelName", "SoftwareVersions",
        "Laterality", "BodyPartExamined",
        "AcquisitionDate", "AcquisitionTime",
        "SOPInstanceUID", "ImageWidth", "ImageHeight",
        # Clinical
        "Diagnosis", "ClinicalNotes"
    }

    # DICOM tags to UI names (when reading pydicom-derived dicts)
    DICOM_TO_UI = {
        # patient
        "PatientName": "PatientName",
        "PatientID": "PatientID",
        "PatientBirthDate": "PatientBirthDate",
        "PatientSex": "PatientSex",
        "PatientAge": "PatientAge",

        # study/series
        "StudyDate": "StudyDate",
        "StudyTime": "StudyTime",
        "StudyDescription": "StudyDescription",
        "SeriesDescription": "SeriesDescription",
        "Modality": "Modality",

        # device
        "Manufacturer": "Manufacturer",
        "ManufacturerModel": "ManufacturerModel",
        "ModelName": "ModelName",
        "SoftwareVersions": "SoftwareVersions",

        # image
        "Laterality": "Laterality",
        "BodyPartExamined": "BodyPartExamined",
        "AcquisitionDate": "AcquisitionDate",
        "AcquisitionTime": "AcquisitionTime",
        "SOPInstanceUID": "SOPInstanceUID",
        "ImageWidth": "ImageWidth",
        "ImageHeight": "ImageHeight",

        # clinical (map multiple sources)
        "AdmittingDiagnoses": "Diagnosis",
        "AdmittingDiagnosesDescription": "Diagnosis",
        "ReasonForTheRequestedProcedure": "Diagnosis",
        "AdditionalPatientHistory": "ClinicalNotes",
        "ClinicalHistory": "ClinicalNotes",
        "StudyComments": "ClinicalNotes",
        "ImageComments": "ClinicalNotes",
    }

    # TIFF/sidecar synonyms to UI names
    TIFF_TO_UI = {
        # often in your sidecars
        "PatientName": "PatientName",
        "PatientID": "PatientID",
        "PatientBirthDate": "PatientBirthDate",
        "PatientSex": "PatientSex",
        "PatientAge": "PatientAge",
        "StudyDate": "StudyDate",
        "StudyTime": "StudyTime",
        "StudyDescription": "StudyDescription",
        "SeriesDescription": "SeriesDescription",
        "Modality": "Modality",
        "Manufacturer": "Manufacturer",
        "ManufacturerModel": "ManufacturerModel",
        "ModelName": "ModelName",
        "SoftwareVersions": "SoftwareVersions",
        "Laterality": "Laterality",
        "BodyPartExamined": "BodyPartExamined",
        "AcquisitionDate": "AcquisitionDate",
        "AcquisitionTime": "AcquisitionTime",
        "SOPInstanceUID": "SOPInstanceUID",
        "ImageWidth": "ImageWidth",
        "ImageHeight": "ImageHeight",
        # clinical fields if present in sidecar JSON
        "Diagnosis": "Diagnosis",
        "ClinicalNotes": "ClinicalNotes",
    }

    def _normalize_dates_times(self, d: Dict[str, Any]) -> None:
        # YYYYMMDD -> YYYY-MM-DD
        for k in ("StudyDate", "AcquisitionDate", "PatientBirthDate"):
            v = d.get(k)
            if isinstance(v, str) and len(v) == 8 and v.isdigit():
                d[k] = f"{v[:4]}-{v[4:6]}-{v[6:8]}"
        # HHMMSS[.ffff] -> HH:MM:SS
        for k in ("StudyTime", "AcquisitionTime"):
            v = d.get(k)
            if isinstance(v, str) and len(v) >= 6 and v.replace(":", "").isdigit():
                v = v.replace(":", "")
                d[k] = f"{v[:2]}:{v[2:4]}:{v[4:6]}"

    def normalize(self, obj) -> Dict[str, Any]:
        """
        Accepts either:
          - DicomFile (has .metadata dict)
          - RegularImage (has .metadata dict)
        Returns a dict containing only keys the UI expects (plus picture_uid if present).
        """
        raw: Dict[str, Any] = {}

        # pull object-level dict
        md = getattr(obj, "metadata", None)
        if isinstance(md, dict):
            raw.update(md)

        # Some loaders keep extra computed fields on the object
        if getattr(obj, "picture_uid", None):
            raw["picture_uid"] = obj.picture_uid

        # Choose mapping
        mapped: Dict[str, Any] = {}
        # Heuristic: if we see typical DICOM keys, use DICOM mapping else TIFF map
        if any(k in raw for k in ("StudyInstanceUID", "SeriesInstanceUID", "PixelSpacing")):
            mapping = self.DICOM_TO_UI
        else:
            mapping = self.TIFF_TO_UI

        # Apply mapping
        for src, dst in mapping.items():
            if src in raw and raw[src] not in (None, "", []):
                val = raw[src]
                # Avoid accidentally stuffing dicts into scalars (bugfix for TIFF sidecar merge)
                if isinstance(val, dict):
                    continue
                mapped[dst] = val

        # carry through any exact UI key already present
        for ui_key in self.UI_KEYS:
            if ui_key in raw and raw[ui_key] not in (None, "", []):
                if isinstance(raw[ui_key], dict):
                    continue
                mapped.setdefault(ui_key, raw[ui_key])

        # Normalize date/time fields
        self._normalize_dates_times(mapped)

        # Derive PatientAge if not provided
        if not mapped.get("PatientAge") and mapped.get("PatientBirthDate") and mapped.get("StudyDate"):
            try:
                b = mapped["PatientBirthDate"].replace("-", "")
                s = mapped["StudyDate"].replace("-", "")
                by, bm, bd = int(b[:4]), int(b[4:6]), int(b[6:8])
                sy, sm, sd = int(s[:4]), int(s[4:6]), int(s[6:8])
                age = sy - by - ((sm, sd) < (bm, bd))
                mapped["PatientAge"] = f"{age:03}Y"
            except Exception:
                pass

        # Provide sensible defaults for display-only (don’t override if present)
        mapped.setdefault("Modality", "OP")
        mapped.setdefault("BodyPartExamined", "EYE")

        return mapped


# Singleton instance
metadata_reader = MetadataReader()
