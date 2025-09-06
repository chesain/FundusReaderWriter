# DICOM Fundus Reader/Writer

A PyQt6 desktop application for viewing, managing, and exporting ophthalmic DICOM images with HIPAA-compliant metadata handling.

## Features

### Core Functionality
- **DICOM Image Viewing**: Load and display fundus DICOM images with zoom/pan capabilities
- **Picture UID Management**: Generate and persist unique identifiers for HIPAA-compliant file linking
- **Metadata Extraction**: Extract and display 7 key DICOM fields plus SOP Instance UID
- **Image Export**: Export DICOM images as TIFF files with Picture UID filenames
- **Metadata Export**: Export metadata as JSON Lines or CSV with de-identification options
- **Bulk Operations**: Process entire directories of DICOM files at once

### Picture UID System
- **Non-PHI Identifier**: Randomly generated UID that links images to metadata without exposing PHI
- **Private Tag Storage**: Stored in DICOM using private creator "VUWindsurf" at (0011,1001)
- **Persistent Linking**: Written back to original DICOM for round-trip consistency
- **HIPAA Compliance**: Enables separation of images and PHI metadata

### UI Components
- **File Browser**: Navigate DICOM files with thumbnail previews
- **Image Viewer**: Pan/zoom with mouse wheel, drag to pan, laterality badges
- **Metadata Panel**: Display all extracted fields with copy-to-clipboard functionality
- **Export Options**: Toggle JSON/CSV export and de-identification

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd FundisReaderWriter
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### Starting the Application

Run the application using:
```bash
python run_app.py
```

Or load a specific directory:
```bash
python run_app.py /path/to/dicom/directory
```

### Workflow

1. **Open Directory**: Click "Open Folder" or press `Ctrl+O` to select a directory containing DICOM files

2. **Browse Images**: 
   - Use the file list on the left to select files
   - Navigate with arrow keys or Previous/Next buttons
   - Images display with laterality badges (L/R) when available

3. **Manage Picture UIDs**:
   - If missing, click "Generate" to create a Picture UID
   - Click "Write" to save the UID back to the DICOM file
   - Use "Copy" to copy UIDs to clipboard

4. **Export Options**:
   - **Export Current Image**: Exports selected image as TIFF
   - **Export Metadata**: Exports metadata for all files
   - **Bulk Export All**: Exports all images and metadata
   - Toggle "De-identify" to remove PHI from exported metadata

### Keyboard Shortcuts
- `Ctrl+O`: Open folder
- `Ctrl+E`: Export current image
- `Ctrl+M`: Export metadata
- `Ctrl+Shift+E`: Bulk export all
- `F`: Fit image to view
- `R`: Reset zoom to 100%
- `←/→`: Navigate files

## Export Formats

### Image Export
- Format: TIFF (8/16-bit preserved)
- Filename: `<picture_uid>.tiff`
- Location: `exports/images/`

### Metadata Export

#### JSON Lines Format (metadata.jsonl)
```json
{
  "picture_uid": "1.2.826.0.1.3680043.9.8223.1.1",
  "sop_instance_uid": "1.2.826.0.1.3680043.214.465905691721174609010740620990936034438",
  "manufacturer_model": "Maestro2",
  "instance_creation_date": "20241022",
  "instance_creation_time": "141931.921",
  "image_laterality": "R",
  "patient_name": "John Doe",
  "patient_id": "12345",
  "patient_birth_date": "19500101",
  "source_file": "image.dcm",
  "export_image": "1.2.826.0.1.3680043.9.8223.1.1.tiff"
}
```

#### CSV Format (metadata.csv)
Standard CSV with headers matching JSON fields

#### De-identified Export
When de-identification is enabled:
- PHI fields (patient_name, patient_id, patient_birth_date) are removed
- A "deidentified": true flag is added

## Technical Details

### DICOM Private Tag Implementation
```python
PRIVATE_CREATOR = "VUWindsurf"
PRIVATE_GROUP = 0x0011
PICTURE_UID_ELEM = 0x1001  # (0011,1001) VR=UI
```

### Supported DICOM Fields
- **(0008,1090)** Manufacturer's Model Name
- **(0008,0012)** Instance Creation Date
- **(0008,0013)** Instance Creation Time
- **(0020,0062)** Image Laterality
- **(0010,0010)** Patient's Name
- **(0010,0020)** Patient ID
- **(0010,0030)** Patient's Birth Date
- **(0008,0018)** SOP Instance UID

### Compression Support
- Handles JPEG Lossless compressed DICOM files via pylibjpeg
- Automatic fallback to Implicit VR Little Endian for missing Transfer Syntax

## Project Structure
```
FundisReaderWriter/
├── app/
│   ├── core/
│   │   ├── dicom_io.py      # DICOM I/O and Picture UID management
│   │   └── export.py         # Export functionality
│   ├── ui/
│   │   ├── main_window.py   # Main application window
│   │   ├── image_viewer.py  # Image display widget
│   │   ├── metadata_panel.py # Metadata display/controls
│   │   └── file_browser.py  # File navigation widget
│   └── main.py              # Application entry point
├── exports/                 # Default export directory
│   ├── images/             # Exported TIFF images
│   └── metadata.jsonl      # Exported metadata
├── requirements.txt        # Python dependencies
├── run_app.py             # Simplified launcher script
└── README.md              # This file
```

## Dependencies
- Python 3.10+
- PyQt6 >= 6.4.0
- pydicom >= 2.4.0
- Pillow >= 10.0.0
- pylibjpeg >= 2.0.0 (for compressed DICOM support)
- numpy >= 1.24.0
- pandas >= 2.0.0 (for CSV export)

## Error Handling
- Missing fields display as "—" in the UI
- Compressed images handled via pylibjpeg pixel handlers
- Graceful fallback for missing Transfer Syntax UID
- Progress dialogs with cancellation for bulk operations

## Security & HIPAA Compliance
- Picture UIDs are randomly generated, never derived from PHI
- PHI never included in filenames
- Export metadata strictly separated from images
- De-identification option removes all PHI fields
- Private tags preserve data integrity without modifying standard fields

## License
[Your License Here]

## Support
For issues or questions, please contact [your contact info]
