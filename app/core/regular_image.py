"""Handler for regular image files (TIFF, PNG, JPEG, etc.)"""
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
import hashlib
from PIL import Image
import numpy as np

logger = logging.getLogger(__name__)

class RegularImageFile:
    """Wrapper for regular image files to provide DICOM-like interface"""
    
    def __init__(self, file_path: str):
        """Initialize with image file path
        
        Args:
            file_path: Path to image file
        """
        self.file_path = Path(file_path)
        self.image = None
        self.metadata = {}
        self.pixel_array = None
        self.picture_uid = None
        
        if not self.file_path.exists():
            raise FileNotFoundError(f"Image file not found: {file_path}")
        
        self._load_image()
        self._extract_metadata()
        
    def _load_image(self):
        """Load the image using PIL"""
        try:
            self.image = Image.open(self.file_path)
            # Convert to RGB if necessary
            if self.image.mode not in ('L', 'RGB', 'RGBA'):
                self.image = self.image.convert('RGB')
            
            # Convert to numpy array
            self.pixel_array = np.array(self.image)
            logger.info(f"Loaded image: {self.file_path.name} ({self.image.size})")
        except Exception as e:
            logger.error(f"Failed to load image {self.file_path}: {e}")
            raise
    
    def _extract_metadata(self):
        """Extract metadata from regular image file"""
        # Basic file info
        self.metadata["source_file"] = self.file_path.name
        self.metadata["file_format"] = self.file_path.suffix.upper()[1:]
        self.metadata["file_size"] = self.file_path.stat().st_size
        
        # Image properties
        if self.image:
            self.metadata["image_width"] = self.image.width
            self.metadata["image_height"] = self.image.height
            self.metadata["image_mode"] = self.image.mode
            
            # Extract EXIF data if available
            if hasattr(self.image, '_getexif') and self.image._getexif():
                try:
                    from PIL.ExifTags import TAGS
                    exif_data = self.image._getexif()
                    for tag, value in exif_data.items():
                        tag_name = TAGS.get(tag, tag)
                        if tag_name == "DateTime":
                            # Format datetime
                            try:
                                dt = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                                self.metadata["acquisition_date"] = dt.strftime("%Y-%m-%d")
                                self.metadata["acquisition_time"] = dt.strftime("%H:%M:%S")
                            except:
                                self.metadata["datetime_original"] = value
                        elif tag_name == "Make":
                            self.metadata["manufacturer"] = value
                        elif tag_name == "Model":
                            self.metadata["manufacturer_model"] = value
                        elif tag_name == "Software":
                            self.metadata["software_versions"] = value
                except Exception as e:
                    logger.debug(f"Could not extract EXIF data: {e}")
            
            # Generate a pseudo SOP Instance UID based on file hash
            with open(self.file_path, 'rb') as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()
            self.metadata["sop_instance_uid"] = f"1.2.826.0.1.{file_hash[:30]}"
        
        # File dates
        stat = self.file_path.stat()
        mod_time = datetime.fromtimestamp(stat.st_mtime)
        self.metadata["file_modified_date"] = mod_time.strftime("%Y-%m-%d")
        self.metadata["file_modified_time"] = mod_time.strftime("%H:%M:%S")
        
    def get_pixel_array(self) -> np.ndarray:
        """Get pixel array for display
        
        Returns:
            Numpy array of pixel data
        """
        return self.pixel_array
    
    def get_image(self) -> Image.Image:
        """Get PIL Image
        
        Returns:
            PIL Image object
        """
        return self.image
    
    def export_to_tiff(self, output_path: Path):
        """Export image to TIFF format
        
        Args:
            output_path: Path for output TIFF file
        """
        if self.image:
            # Save as TIFF
            self.image.save(output_path, format='TIFF', compression='tiff_lzw')
            logger.info(f"Exported to TIFF: {output_path}")
    
    def generate_picture_uid(self, use_hmac: bool = False, secret: str = None) -> str:
        """Generate Picture UID for regular image
        
        Args:
            use_hmac: Whether to use HMAC (ignored for regular images)
            secret: Secret key for HMAC (ignored for regular images)
            
        Returns:
            Generated Picture UID
        """
        # Use file hash for Picture UID
        with open(self.file_path, 'rb') as f:
            file_content = f.read()
        
        uid_hash = hashlib.sha256(file_content).hexdigest()[:32]
        self.picture_uid = uid_hash
        logger.info(f"Generated Picture UID for {self.file_path.name}: {uid_hash}")
        return uid_hash
    
    def write_picture_uid(self, output_path: Optional[Path] = None):
        """For regular images, we can't write UID to the file itself
        
        Args:
            output_path: Optional path to save metadata
        """
        logger.info(f"Picture UID for regular images is stored in memory only")
        # Could optionally save to a sidecar file
        if output_path:
            import json
            metadata_path = output_path.with_suffix('.json')
            with open(metadata_path, 'w') as f:
                json.dump({
                    'picture_uid': self.picture_uid,
                    'source_file': str(self.file_path),
                    'metadata': self.metadata
                }, f, indent=2)
            logger.info(f"Saved metadata to: {metadata_path}")
