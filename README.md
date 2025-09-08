# DICOM / TIFF Reader & Writer

A lightweight desktop app (PyQt6) for **reading** DICOM and TIFF fundus images, viewing pixels, and **writing** exports (TIFF + per-image JSON sidecars). It shows a DICOM-style metadata panel and can batch-export images with stable filenames (using the SOP Instance UID when available).

---

## Features

- **Read**:
  - DICOM (`.dcm`, `.dicom`, or extensionless with DICM preamble)
  - TIFF/OME-TIFF (`.tif`, `.tiff`)
- **View**:
  - Wheel zoom, hand-drag pan, **Fit to View**
  - Previous/Next file navigation
- **Write**:
  - **Per-image** TIFF export (8-bit RGB/Grayscale)
  - **Per-image JSON** sidecar (no global JSONL), including `picture_uid`
- **Metadata panel** (read-only):
  - Patient/Study/Series details
  - Diagnostic fields (e.g., Diagnosis, DiagnosisCodes, ReasonForRequestedProcedure, StudyComments, ClinicalNotes)
  - Dimensions, SOP Instance UID
  - **PatientAge** (taken from DICOM if present, otherwise computed from Birth Date + Study/Acquisition Date when possible)

> **Note on identifiers**
>
> `SOPInstanceUID` is globally unique per DICOM instance and is used as the preferred export filename stem. If missing, the app falls back to a stable `picture_uid` and auto-dedupes with `-2`, `-3`, … to avoid overwrites.

---

## Quick Start

### 1) Create & activate a virtual environment

```bash
# macOS/Linux (bash/zsh)
python3 -m venv .venv
source .venv/bin/activate

# Windows (PowerShell)
py -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2) Install dependencies

```bash
pip install -r requirements.txt
```

### 3) Run the app

```bash
python run_app.py
```

---

## Using the App

### Open images

- **Open Image…**: load a single DICOM/TIFF
- **Open Folder…**: recursively loads all supported images; use **Previous/Next** to move through the list

### View controls

- **Mouse wheel**: Zoom in/out
- **Drag**: Pan (hand tool)
- **Fit to View**: Menu: _Navigate → Fit to View_ (or toolbar button if present)

### Write (exports)

- **Export Current**: saves one image to `<chosen>/images/<stem>.tiff` and sidecar `<stem>.json`
- **Bulk Export…**: exports all loaded items to the same `images/` folder with **no overwrite** (adds `-2`, `-3`, … when needed)

**Export naming**

- Preferred stem: `SOPInstanceUID`
- Else: `picture_uid` (created by the app)
- Else: running sequence (`0001`, `0002`, …)

Each export writes:

- **TIFF** (8-bit, RGB or L)
- **JSON** sidecar with all panel metadata plus:
  - `picture_uid` (the chosen basename)
  - `SourceFile` (exported TIFF filename)
  - `ImageWidth` / `ImageHeight` sanity values

---

## Patient Age logic

The panel shows **PatientAge** from the DICOM tag if available.  
If missing, the app computes age (in years) from **Birth Date** and the best available date among **Study Date** or **Acquisition Date**.

---

## Project Structure

```
FundusReaderWriter/
├─ run_app.py
├─ requirements.txt
├─ app/
│  ├─ core/
│  │  ├─ dicom_io.py        # DICOM read + metadata extraction
│  │  └─ tiff_reader.py     # TIFF read + metadata (tags/XMP/sidecars)
│  └─ ui/
│     ├─ main_window.py     # Reader & Writer UI (list + viewer + metadata)
│     ├─ image_viewer.py    # Zoom/Pan/Fit viewer
│     └─ metadata_panel.py  # Read-only DICOM-style fields
```

---

## Shortcuts & Menu

- **Open Image…**, **Open Folder…**
- **Previous / Next** (navigate file list)
- **Export Current**, **Bulk Export…**
- **Fit to View** (resets zoom to fit the window)

---

## Troubleshooting

- **No pixel shown for DICOM**  
  Some compressed transfer syntaxes require optional plugins. This app preconfigures common pydicom handlers and will fall back gracefully. If a specific file still fails, ensure JPEG plugins are installed (see `requirements.txt`) and try again.
- **TIFF metadata empty**  
  The app merges embedded XMP/TIFF tags **and** per-image JSON sidecars. Ensure the exported JSON files are next to the TIFFs (same basename) or under a nearby `metadata/` folder.

---
