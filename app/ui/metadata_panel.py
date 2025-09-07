from typing import Dict, Any
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QLineEdit, QTextEdit, QVBoxLayout, QScrollArea
)

FIELD_ORDER = [
    "PatientName", "PatientID", "PatientBirthDate", "PatientAge", "PatientSex",
    "StudyDate", "StudyTime", "StudyDescription", "SeriesDescription",
    "Modality", "Manufacturer", "ManufacturerModel", "ModelName",
    "SoftwareVersions", "Laterality", "BodyPartExamined",
    # Diagnostic-ish
    "Diagnosis", "DiagnosisCodes", "ReasonForRequestedProcedure",
    "StudyComments", "ClinicalNotes",
    # Dimensions
    "Width", "Height", "SOPInstanceUID"
]

TEXTAREA_FIELDS = {"Diagnosis", "DiagnosisCodes", "ReasonForRequestedProcedure", "StudyComments", "ClinicalNotes"}

class MetadataPanel(QWidget):
    """
    Read-only form with scroll.
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        self._edits: Dict[str, QLineEdit | QTextEdit] = {}

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)

        for key in FIELD_ORDER:
            if key in TEXTAREA_FIELDS:
                w = QTextEdit(self)
                w.setReadOnly(True)
                w.setFixedHeight(64)
            else:
                w = QLineEdit(self)
                w.setReadOnly(True)
            self._edits[key] = w
            form.addRow(f"{key.replace('_',' ')}:", w)

        inner = QWidget()
        inner.setLayout(form)
        scroll = QScrollArea(self)
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)

        outer = QVBoxLayout(self)
        outer.addWidget(scroll)

    def set_metadata(self, meta: Dict[str, Any]):
        for key, widget in self._edits.items():
            val = meta.get(key, "")  # show nothing if absent
            if isinstance(widget, QTextEdit):
                widget.setPlainText(str(val))
            else:
                widget.setText(str(val))

    # Used by export buttons for options if you later add toggles
    def get_export_options(self) -> dict:
        return {}
