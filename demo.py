#!/usr/bin/env python3
"""
Demo script to test DICOM Reader/Writer functionality
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.dicom_io import DicomDirectory, DicomFile, initialize_dicom_environment
from app.core.export import Exporter, ExportConfig
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def demo_cli_export():
    """Demonstrate CLI export functionality"""
    # Prewarm DICOM environment to avoid first-try failures
    try:
        initialize_dicom_environment()
    except Exception:
        pass
    # Find DICOM directory
    base_dir = Path(__file__).parent
    dicom_dirs = [
        base_dir / "1.2.826.0.1.3680043.214.48881084531741188492693918414548673959",
    ]
    
    # Find first directory with DICOM files
    dicom_dir = None
    for d in dicom_dirs:
        if d.exists():
            dicom_dir = d
            break
    
    if not dicom_dir:
        logger.error("No DICOM directories found")
        return
    
    print(f"\n📁 Loading DICOM files from: {dicom_dir}")
    print("=" * 60)
    
    # Load directory
    directory = DicomDirectory(dicom_dir)
    print(f"✓ Found {directory.get_file_count()} DICOM files")
    
    # Display file information
    print("\n📋 File Information:")
    print("-" * 60)
    for i, dicom_file in enumerate(directory.dicom_files[:3], 1):  # Show first 3
        print(f"\n{i}. {dicom_file.file_path.name}")
        print(f"   • SOP Instance UID: {dicom_file.metadata.get('sop_instance_uid', 'N/A')}")
        print(f"   • Laterality: {dicom_file.metadata.get('image_laterality', 'N/A')}")
        print(f"   • Patient ID: {dicom_file.metadata.get('patient_id', 'N/A')}")
        print(f"   • Picture UID: {dicom_file.picture_uid or 'Not generated'}")
    
    # Generate Picture UIDs
    print("\n🔑 Generating Picture UIDs...")
    print("-" * 60)
    for dicom_file in directory.dicom_files:
        if not dicom_file.picture_uid:
            uid = dicom_file.generate_picture_uid()
            print(f"✓ Generated UID for {dicom_file.file_path.name}")
            print(f"  → {uid}")
    
    # Export demonstration
    export_dir = base_dir / "demo_exports"
    print(f"\n📤 Exporting to: {export_dir}")
    print("=" * 60)
    
    exporter = Exporter(export_dir)
    
    # Export single image
    if directory.dicom_files:
        first_file = directory.dicom_files[0]
        image_path = exporter.export_single_image(first_file)
        print(f"✓ Exported image: {image_path.name}")
    
    # Export metadata (both JSON and CSV)
    metadata_paths = exporter.export_metadata(
        directory.dicom_files,
        deidentify=False,
        export_csv=True
    )
    print(f"✓ Exported metadata:")
    for format_type, path in metadata_paths.items():
        print(f"  • {format_type}: {Path(path).name}")
    
    # Show de-identification example
    print("\n🔒 De-identification Example:")
    print("-" * 60)
    if directory.dicom_files:
        sample_file = directory.dicom_files[0]
        
        # Normal export
        normal_meta = sample_file.get_metadata_for_export(deidentify=False)
        print("Normal export includes:")
        for key in ["patient_name", "patient_id", "patient_birth_date"]:
            if key in normal_meta:
                print(f"  • {key}: {normal_meta[key]}")
        
        # De-identified export
        deid_meta = sample_file.get_metadata_for_export(deidentify=True)
        print("\nDe-identified export:")
        print(f"  • PHI removed: {', '.join(['patient_name', 'patient_id', 'patient_birth_date'])}")
        print(f"  • Flag added: deidentified = {deid_meta.get('deidentified', False)}")
    
    print("\n✅ Demo complete! Check the 'demo_exports' folder for outputs.")
    print("\n💡 To launch the GUI application, run: python run_app.py")

if __name__ == "__main__":
    demo_cli_export()
