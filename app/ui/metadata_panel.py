"""
Metadata panel widget for displaying DICOM metadata
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QFrame,
    QApplication, QScrollArea, QTextEdit
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QClipboard, QGuiApplication
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class MetadataPanel(QWidget):
    """Panel for displaying and managing DICOM metadata"""
    
    # Signals
    generate_uid_requested = pyqtSignal()
    write_uid_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_metadata = {}
        self.picture_uid = None
        self._init_ui()
    
    def _init_ui(self):
        """Setup the UI layout"""
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("DICOM Metadata")
        title.setStyleSheet("""
            font-size: 16px;
            font-weight: bold;
            margin-bottom: 10px;
            color: #2196F3;
        """)
        layout.addWidget(title)
        
        # Scroll area for metadata
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        
        # Basic Information Section
        basic_title = QLabel("Basic Information")
        basic_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #ffffff; margin-top: 5px; background: transparent;")
        scroll_layout.addWidget(basic_title)
        
        # Metadata fields
        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_layout.setSpacing(8)
        
        # Create fields
        self.fields = {}
        field_names = [
            "manufacturer_model",
            "instance_creation_date",
            "instance_creation_time",
            "image_laterality",
            "patient_name",
            "patient_id",
            "patient_birth_date"
        ]
        
        label_style = """
            QLabel {
                color: #ffffff;
                font-weight: 500;
                font-size: 12px;
                background: transparent;
            }
        """
        field_style = """
            QLineEdit {
                background-color: #f5f5f5;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 5px;
                color: #333;
                font-size: 12px;
            }
            QLineEdit:read-only {
                background-color: #f9f9f9;
            }
        """
        
        for field_name in field_names:
            label = QLabel(field_name.replace('_', ' ').title() + ":")
            label.setMinimumWidth(140)
            label.setStyleSheet(label_style)
            
            field = QLineEdit()
            field.setReadOnly(True)
            field.setText("—")
            field.setStyleSheet(field_style)
            
            self.fields[field_name] = field
            form_layout.addRow(label, field)
        
        # SOP Instance UID with copy button
        sop_layout = QHBoxLayout()
        sop_label = QLabel("SOP Instance UID:")
        sop_label.setMinimumWidth(140)
        sop_label.setStyleSheet(label_style)
        self.sop_uid_field = QLineEdit()
        self.sop_uid_field.setReadOnly(True)
        self.sop_uid_field.setText("—")
        self.sop_uid_field.setStyleSheet(field_style)
        self.sop_copy_btn = QPushButton("Copy")
        self.sop_copy_btn.setMaximumWidth(60)
        self.sop_copy_btn.clicked.connect(self._copy_sop_uid)
        self.sop_copy_btn.setEnabled(False)
        self.sop_copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:disabled {
                background-color: #ccc;
            }
        """)
        
        form_layout.addRow(sop_label, sop_layout)
        sop_layout.addWidget(self.sop_uid_field)
        sop_layout.addWidget(self.sop_copy_btn)
        
        # Picture UID section
        scroll_layout.addWidget(QFrame())
        pic_uid_layout = QHBoxLayout()
        uid_label = QLabel("Picture UID:")
        uid_label.setMinimumWidth(140)
        uid_label.setStyleSheet(label_style)
        self.pic_uid_field = QLineEdit()
        self.pic_uid_field.setReadOnly(True)
        self.pic_uid_field.setText("—")
        self.pic_uid_field.setStyleSheet(field_style)
        
        button_style = """
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 5px 10px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #ccc;
            }
        """
        
        self.generate_btn = QPushButton("Generate")
        self.generate_btn.clicked.connect(self._generate_uid)
        self.generate_btn.setStyleSheet(button_style)
        self.write_btn = QPushButton("Write")
        self.write_btn.clicked.connect(self._write_uid)
        self.write_btn.setEnabled(False)
        self.write_btn.setStyleSheet(button_style.replace("#4CAF50", "#FF9800").replace("#45a049", "#F57C00"))
        self.pic_uid_copy_btn = QPushButton("Copy")
        self.pic_uid_copy_btn.clicked.connect(self._copy_pic_uid)
        self.pic_uid_copy_btn.setEnabled(False)
        self.pic_uid_copy_btn.setStyleSheet(button_style.replace("#4CAF50", "#2196F3").replace("#45a049", "#1976D2"))
        
        pic_uid_layout.addWidget(self.pic_uid_field)
        pic_uid_layout.addWidget(self.generate_btn)
        pic_uid_layout.addWidget(self.write_btn)
        pic_uid_layout.addWidget(self.pic_uid_copy_btn)
        
        form_layout.addRow(uid_label, pic_uid_layout)
        
        scroll_layout.addLayout(form_layout)
        
        # Diagnosis & Clinical Information Section
        diag_title = QLabel("Diagnosis & Clinical Information")
        diag_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #ffffff; margin-top: 15px; background: transparent;")
        scroll_layout.addWidget(diag_title)
        
        diag_form = QFormLayout()
        diag_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        diag_form.setSpacing(8)
        
        diagnosis_fields = [
            "study_description",
            "series_description",
            "clinical_history",
            "admitting_diagnoses",
            "additional_patient_history",
            "image_comments"
        ]
        
        for field_name in diagnosis_fields:
            label = QLabel(field_name.replace('_', ' ').title() + ":")
            label.setMinimumWidth(140)
            label.setStyleSheet(label_style)
            
            if field_name in ["clinical_history", "additional_patient_history", "image_comments"]:
                # Use text edit for longer fields
                field = QTextEdit()
                field.setMaximumHeight(60)
                field.setReadOnly(True)
                field.setPlainText("—")
                field.setStyleSheet(field_style.replace("QLineEdit", "QTextEdit"))
            else:
                field = QLineEdit()
                field.setReadOnly(True)
                field.setText("—")
                field.setStyleSheet(field_style)
            
            self.fields[field_name] = field
            diag_form.addRow(label, field)
        
        scroll_layout.addLayout(diag_form)
        
        # Picture UID Section
        uid_title = QLabel("Picture UID")
        uid_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #ffffff; margin-top: 15px; background: transparent;")
        scroll_layout.addWidget(uid_title)
        
        # Export Options Section
        export_title = QLabel("Export Options")
        export_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #ffffff; margin-top: 15px; background: transparent;")
        scroll_layout.addWidget(export_title)
        
        # Export checkboxes
        checkbox_style = """
            QCheckBox {
                color: #ffffff;
                font-size: 12px;
                background: transparent;
            }
        """
        
        self.export_json_cb = QCheckBox("Export as JSON Lines")
        self.export_json_cb.setChecked(True)
        self.export_json_cb.setStyleSheet(checkbox_style)
        
        self.export_csv_cb = QCheckBox("Export as CSV")
        self.export_csv_cb.setStyleSheet(checkbox_style)
        
        self.deidentify_cb = QCheckBox("De-identify (remove PHI)")
        self.deidentify_cb.setStyleSheet(checkbox_style)
        
        scroll_layout.addWidget(self.export_json_cb)
        scroll_layout.addWidget(self.export_csv_cb)
        scroll_layout.addWidget(self.deidentify_cb)
        
        # Add scroll widget to main layout
        scroll.setWidget(scroll_widget)
        scroll_layout.addStretch()
        layout.addWidget(scroll)
    
    def update_metadata(self, dicom_file):
        """Update displayed metadata"""
        self.current_file = dicom_file
        
        if not dicom_file:
            # Clear all fields
            for field in self.fields.values():
                if isinstance(field, QTextEdit):
                    field.setPlainText("—")
                else:
                    field.setText("—")
            self.sop_uid_field.setText("—")
            self.pic_uid_field.setText("—")
            self.generate_btn.setEnabled(False)
            self.write_btn.setEnabled(False)
            self.sop_copy_btn.setEnabled(False)
            self.pic_uid_copy_btn.setEnabled(False)
            return
        
        # Update fields
        for field_name, field_widget in self.fields.items():
            value = dicom_file.metadata.get(field_name)
            if value:
                if isinstance(field_widget, QTextEdit):
                    field_widget.setPlainText(str(value))
                else:
                    field_widget.setText(str(value))
            else:
                if isinstance(field_widget, QTextEdit):
                    field_widget.setPlainText("—")
                else:
                    field_widget.setText("—")
            self.write_btn.setEnabled(False)
    
        # Update SOP UID
        sop_uid = dicom_file.metadata.get("sop_instance_uid")
        if sop_uid:
            self.sop_uid_field.setText(str(sop_uid))
            self.sop_copy_btn.setEnabled(True)
        else:
            self.sop_uid_field.setText("—")
            self.sop_copy_btn.setEnabled(False)
        
        # Update Picture UID
        if dicom_file.picture_uid:
            self.pic_uid_field.setText(dicom_file.picture_uid)
            self.generate_btn.setEnabled(False)
            self.write_btn.setEnabled(False)
            self.pic_uid_copy_btn.setEnabled(True)
        else:
            self.pic_uid_field.setText("—")
            self.generate_btn.setEnabled(True)
            self.write_btn.setEnabled(False)
            self.pic_uid_copy_btn.setEnabled(False)
    
    def _copy_sop_uid(self):
        """Copy SOP UID to clipboard"""
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(self.sop_uid_field.text())
        logger.info("Copied SOP UID to clipboard")
    
    def _copy_pic_uid(self):
        """Copy Picture UID to clipboard"""
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(self.pic_uid_field.text())
        logger.info("Copied Picture UID to clipboard")
    
    def _generate_uid(self):
        """Generate a new Picture UID"""
        self.generate_uid_requested.emit()
    
    def _write_uid(self):
        """Write Picture UID to DICOM file"""
        self.write_uid_requested.emit()
    
    def set_picture_uid(self, uid: str):
        """Set the Picture UID after generation"""
        self.pic_uid_field.setText(uid)
        self.pic_uid_field.setStyleSheet("QLineEdit { background-color: #fff3cd; }")  # Light yellow
        self.generate_btn.setEnabled(False)
        self.write_btn.setEnabled(True)
        self.pic_uid_copy_btn.setEnabled(True)
    
    def mark_uid_written(self):
        """Mark that UID has been written to DICOM"""
        self.pic_uid_field.setStyleSheet("QLineEdit { background-color: #d4f0d4; }")  # Light green
        self.write_btn.setEnabled(False)
    
    def get_export_options(self) -> Dict[str, bool]:
        """Get current export options"""
        return {
            "export_json": self.export_json_cb.isChecked(),
            "export_csv": self.export_csv_cb.isChecked(),
            "deidentify": self.deidentify_cb.isChecked()
        }
    
    def clear(self):
        """Clear all metadata fields"""
        for field in self.fields.values():
            if isinstance(field, QTextEdit):
                field.setPlainText("—")
            else:
                field.setText("—")
        self.sop_uid_field.setText("—")
        self.pic_uid_field.setText("—")
        self.current_file = None
        self.generate_btn.setEnabled(False)
        self.write_btn.setEnabled(False)
        self.sop_copy_btn.setEnabled(False)
        self.pic_uid_copy_btn.setEnabled(False)
