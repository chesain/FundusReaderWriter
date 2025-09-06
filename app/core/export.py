"""
Export functionality for images and metadata
"""
from pathlib import Path
from typing import List, Dict, Any, Optional
import json
import csv
import logging
from .dicom_io import DicomFile, DicomDirectory

logger = logging.getLogger(__name__)


class Exporter:
    """Handle export operations for DICOM files"""
    
    def __init__(self, export_dir: Path):
        self.export_dir = export_dir
        self.images_dir = export_dir / "images"
        self.metadata_path = export_dir / "metadata.jsonl"
        self.csv_path = export_dir / "metadata.csv"
        self._setup_directories()
    
    def _setup_directories(self):
        """Create export directories"""
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(exist_ok=True)
        logger.info(f"Export directories created at {self.export_dir}")
    
    def export_single_image(self, dicom_file: DicomFile) -> Path:
        """Export a single DICOM image as TIFF"""        
        # Ensure Picture UID exists first (before any DICOM operations)
        if not dicom_file.picture_uid:
            dicom_file.generate_picture_uid()
        
        # Export image with Picture UID as filename
        output_path = self.images_dir / f"{dicom_file.picture_uid}.tiff"
        dicom_file.export_image(output_path, format="TIFF")
        logger.info(f"Exported image to {output_path}")
        return output_path
    
    def export_metadata(self, dicom_files: List[DicomFile], 
                       deidentify: bool = False,
                       export_csv: bool = False) -> Dict[str, Path]:
        """Export metadata for multiple DICOM files"""
        results = {"jsonl": self.metadata_path}
        
        # Collect all metadata
        all_metadata = []
        for dicom_file in dicom_files:
            metadata = dicom_file.get_metadata_for_export(deidentify)
            
            # Add export image filename if Picture UID exists
            if dicom_file.picture_uid:
                metadata["export_image"] = f"{dicom_file.picture_uid}.tiff"
            
            all_metadata.append(metadata)
        
        # Write JSON Lines
        with open(self.metadata_path, 'w', encoding='utf-8') as f:
            for metadata in all_metadata:
                f.write(json.dumps(metadata, default=str) + '\n')
        
        logger.info(f"Exported metadata to {self.metadata_path}")
        
        # Optionally export CSV
        if export_csv and all_metadata:
            results["csv"] = self._export_csv(all_metadata)
        
        return results
    
    def _export_csv(self, metadata_list: List[Dict[str, Any]]) -> Path:
        """Export metadata as CSV"""
        if not metadata_list:
            return self.csv_path
        
        # Get all unique keys across all metadata
        all_keys = set()
        for metadata in metadata_list:
            all_keys.update(metadata.keys())
        
        # Sort keys for consistent column order
        fieldnames = sorted(all_keys)
        
        # Write CSV
        with open(self.csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for metadata in metadata_list:
                # Convert all values to strings for CSV
                row = {k: str(v) if v is not None else '' for k, v in metadata.items()}
                writer.writerow(row)
        
        logger.info(f"Exported CSV to {self.csv_path}")
        return self.csv_path
    
    def bulk_export(self, dicom_directory: DicomDirectory,
                   deidentify: bool = False,
                   export_csv: bool = False,
                   write_uids: bool = False,
                   progress_callback=None) -> Dict[str, Any]:
        """Bulk export all DICOM files in directory"""
        results = {
            "images": [],
            "metadata": None,
            "errors": []
        }
        
        total_files = dicom_directory.get_file_count()
        
        # Process each DICOM file
        for i, dicom_file in enumerate(dicom_directory.dicom_files):
            try:
                # Update progress
                if progress_callback:
                    progress_callback(i + 1, total_files, f"Processing {dicom_file.file_path.name}")
                
                # Pre-load pixel data to cache the full dataset (fixes first-try failures)
                _ = dicom_file.get_pixel_array()
                
                # Ensure Picture UID
                if not dicom_file.picture_uid:
                    dicom_file.generate_picture_uid()
                    if write_uids:
                        dicom_file.write_picture_uid(save=True)
                
                # Export image
                image_path = self.export_single_image(dicom_file)
                results["images"].append(str(image_path))
                
            except Exception as e:
                error_msg = f"Failed to export {dicom_file.file_path.name}: {e}"
                logger.error(error_msg)
                results["errors"].append(error_msg)
        
        # Export metadata
        try:
            metadata_paths = self.export_metadata(
                dicom_directory.dicom_files,
                deidentify=deidentify,
                export_csv=export_csv
            )
            results["metadata"] = {k: str(v) for k, v in metadata_paths.items()}
        except Exception as e:
            error_msg = f"Failed to export metadata: {e}"
            logger.error(error_msg)
            results["errors"].append(error_msg)
        
        return results


class ExportConfig:
    """Configuration for export operations"""
    
    def __init__(self):
        self.deidentify = False
        self.export_csv = False
        self.write_uids_to_dicom = False
        self.export_dir = Path("exports")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "deidentify": self.deidentify,
            "export_csv": self.export_csv,
            "write_uids_to_dicom": self.write_uids_to_dicom,
            "export_dir": str(self.export_dir)
        }
    
    def from_dict(self, data: Dict[str, Any]):
        """Load from dictionary"""
        self.deidentify = data.get("deidentify", False)
        self.export_csv = data.get("export_csv", False)
        self.write_uids_to_dicom = data.get("write_uids_to_dicom", False)
        self.export_dir = Path(data.get("export_dir", "exports"))
