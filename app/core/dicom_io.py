"""
DICOM I/O operations with Picture UID management
"""
from pathlib import Path
from typing import Dict, Any, Optional, List
import pydicom
from pydicom.uid import ImplicitVRLittleEndian
import numpy as np
from PIL import Image
import hashlib
import hmac
import os
import logging

# Import JPEG decompression support
try:
    import pylibjpeg
    JPEG_SUPPORT = True
except ImportError:
    JPEG_SUPPORT = False
    logging.warning("pylibjpeg not available - JPEG compressed DICOM files may not load")

logger = logging.getLogger(__name__)

# Module-level sentinel to avoid repeated environment init
_ENV_INITIALIZED = False

# Configuration
PRIVATE_CREATOR = "VUWindsurf"
PRIVATE_GROUP = 0x0011
PICTURE_UID_ELEM = 0x1001  # (0011,1001) VR=UI

# DICOM metadata fields to extract
METADATA_FIELDS = {
    "manufacturer_model": (0x0008, 0x1090),  # Manufacturer's Model Name
    "instance_creation_date": (0x0008, 0x0012),  # Instance Creation Date
    "instance_creation_time": (0x0008, 0x0013),  # Instance Creation Time
    "image_laterality": (0x0020, 0x0062),  # Image Laterality
    "patient_name": (0x0010, 0x0010),  # Patient's Name
    "patient_id": (0x0010, 0x0020),  # Patient ID
    "patient_birth_date": (0x0010, 0x0030),  # Patient's Birth Date
    "sop_instance_uid": (0x0008, 0x0018),  # SOP Instance UID
    # Diagnosis fields
    "clinical_history": (0x0040, 0x2000),  # Clinical History
    "admitting_diagnoses": (0x0008, 0x1080),  # Admitting Diagnoses Description
    "additional_patient_history": (0x0010, 0x21B0),  # Additional Patient History
    "image_comments": (0x0020, 0x4000),  # Image Comments
    "study_description": (0x0008, 0x1030),  # Study Description
    "series_description": (0x0008, 0x103E),  # Series Description
}

PHI_FIELDS = {"patient_name", "patient_id", "patient_birth_date"}


def initialize_dicom_environment():
    """Initialize pydicom environment, pixel handlers, and warm-up decoding.

    Intended to be called once on app startup to prevent first-try
    failures due to lazy imports or handler initialization.
    """
    global _ENV_INITIALIZED
    if _ENV_INITIALIZED:
        return
    try:
        import pydicom.config
        from pydicom.pixel_data_handlers import numpy_handler, pillow_handler
        handlers = []
        if JPEG_SUPPORT:
            try:
                from pydicom.pixel_data_handlers import pylibjpeg_handler
                # Attempt to import pylibjpeg plugins to ensure availability
                try:
                    import pylibjpeg.libjpeg  # noqa: F401
                except Exception:
                    pass
                try:
                    import pylibjpeg.openjpeg  # noqa: F401
                except Exception:
                    pass
                handlers.append(pylibjpeg_handler)
            except Exception:
                pass
        handlers.extend([numpy_handler, pillow_handler])

        try:
            pydicom.config.pixel_data_handlers = handlers
        except Exception:
            pass

        # Make parsing tolerant
        try:
            pydicom.config.enforce_valid_values = False
            pydicom.config.convert_wrong_length_to_UN = True
        except Exception:
            pass

        # In-memory warm-up using a tiny uncompressed image
        try:
            from pydicom.dataset import Dataset, FileMetaDataset
            from pydicom.uid import ImplicitVRLittleEndian
            ds = Dataset()
            ds.file_meta = FileMetaDataset()
            ds.file_meta.TransferSyntaxUID = ImplicitVRLittleEndian
            ds.is_little_endian = True
            ds.is_implicit_VR = True
            ds.Rows = 2
            ds.Columns = 2
            ds.BitsAllocated = 8
            ds.SamplesPerPixel = 1
            ds.PixelRepresentation = 0
            ds.PhotometricInterpretation = "MONOCHROME2"
            ds.PixelData = bytes([0, 64, 128, 255])
            _ = ds.pixel_array  # Trigger handler init
        except Exception:
            pass

        _ENV_INITIALIZED = True
        logger.info("DICOM environment initialized (handlers configured, warm-up done)")
    except Exception as e:
        logger.debug(f"Failed to initialize DICOM environment: {e}")


class DicomFile:
    """Wrapper for DICOM file operations"""
    
    def __init__(self, file_path: str):
        """Initialize with DICOM file path
        
        Args:
            file_path: Path to DICOM file
        """
        self.file_path = Path(file_path)
        self.dataset: Optional[pydicom.Dataset] = None
        self.metadata: Dict[str, Any] = {}
        self.picture_uid: Optional[str] = None
        self._pixel_array: Optional[np.ndarray] = None
        self._load_header()
    
    def _load_header(self):
        """Load DICOM header without pixel data"""
        try:
            # Tolerant header read to avoid first-try parser errors
            try:
                self.dataset = pydicom.dcmread(
                    str(self.file_path),
                    stop_before_pixels=True,
                    force=True,
                    defer_size=1024,
                )
            except Exception:
                # Fallback: force=True without defer
                self.dataset = pydicom.dcmread(
                    str(self.file_path),
                    stop_before_pixels=True,
                    force=True,
                )
            # Ensure a sane Transfer Syntax for later pixel decoding
            if self.dataset is not None:
                self._ensure_transfer_syntax(self.dataset)
            self._extract_metadata()
            self._get_picture_uid()
        except Exception as e:
            logger.error(f"Failed to load DICOM header {self.file_path}: {e}")
            raise
    
    def _extract_metadata(self):
        """Extract metadata fields from DICOM"""
        for field_name, tag in METADATA_FIELDS.items():
            value = self._get_tag_value(tag)
            if value is not None:
                # Convert to string for JSON serialization
                if hasattr(value, 'original_string'):
                    value = value.original_string
                elif hasattr(value, '__str__'):
                    value = str(value)
                
                # Format dates and times for display
                if field_name.endswith('_date') and len(str(value)) == 8:
                    # Format YYYYMMDD to YYYY-MM-DD
                    value = f"{value[:4]}-{value[4:6]}-{value[6:8]}"
                elif field_name.endswith('_time') and len(str(value)) >= 6:
                    # Format HHMMSS.ffffff to HH:MM:SS
                    value = f"{value[:2]}:{value[2:4]}:{value[4:6]}"
            self.metadata[field_name] = value
        
        # Add filename
        self.metadata["source_file"] = self.file_path.name
    
    def _get_tag_value(self, tag):
        """Get value from DICOM tag"""
        if self.dataset and tag in self.dataset:
            elem = self.dataset[tag]
            if elem.value is not None and elem.value != '':
                return elem.value
        return None
    
    def _get_picture_uid(self):
        """Get Picture UID from private tag if exists"""
        try:
            if self.dataset:
                block = self.dataset.private_block(PRIVATE_GROUP, PRIVATE_CREATOR)
                if block:
                    elem = block.get(PICTURE_UID_ELEM)
                    if elem and elem.value:
                        self.picture_uid = elem.value
        except Exception:
            pass  # No Picture UID yet
    
    def _ensure_transfer_syntax(self, ds):
        """Ensure dataset has a TransferSyntaxUID, set to Implicit VR Little Endian if missing"""
        try:
            fm = getattr(ds, 'file_meta', None)
            if fm is None:
                ds.file_meta = pydicom.dataset.FileMetaDataset()
                fm = ds.file_meta
            if not hasattr(fm, 'TransferSyntaxUID') or fm.TransferSyntaxUID is None:
                fm.TransferSyntaxUID = ImplicitVRLittleEndian
        except Exception:
            # Best-effort; don't fail pre-emptively
            pass
    
    def generate_picture_uid(self) -> str:
        """Generate and assign a new Picture UID"""
        self.picture_uid = pydicom.uid.generate_uid()
        return self.picture_uid
    
    def write_picture_uid(self, save: bool = True):
        """Write Picture UID to DICOM private tag"""
        if not self.picture_uid:
            self.generate_picture_uid()
        
        # Skip UID writing if save=False to avoid DICOM reading issues
        if not save:
            return self.picture_uid
            
        # Ensure we have the full dataset - if we only have header, we need to reload
        if not self.dataset or not hasattr(self.dataset, 'PixelData'):
            # Use the same robust reading approach as get_pixel_array()
            self._prewarm_dicom_reading()
            
            # Try the same approaches as get_pixel_array but just for dataset loading
            approaches = [
                lambda: pydicom.dcmread(str(self.file_path), force=True, defer_size=1024),
                lambda: pydicom.dcmread(str(self.file_path), force=True, defer_size=10*1024),
                lambda: pydicom.dcmread(str(self.file_path), force=True)
            ]
            
            dataset_loaded = False
            for i, approach in enumerate(approaches):
                try:
                    self.dataset = approach()
                    dataset_loaded = True
                    logger.debug(f"Dataset loaded on approach {i+1} for {self.file_path.name}")
                    break
                except Exception as e:
                    logger.debug(f"Dataset loading approach {i+1} failed: {e}")
                    continue
            
            if not dataset_loaded:
                raise Exception("Failed to load full DICOM dataset for UID writing")
            
        # Handle missing TransferSyntaxUID
        if not hasattr(self.dataset.file_meta, 'TransferSyntaxUID'):
            self.dataset.file_meta.TransferSyntaxUID = ImplicitVRLittleEndian
        
        # Create or get private block
        block = self.dataset.private_block(PRIVATE_GROUP, PRIVATE_CREATOR, create=True)
        
        # Add Picture UID to private tag
        block.add_new(PICTURE_UID_ELEM, "UI", self.picture_uid)
        
        if save:
            self.dataset.save_as(str(self.file_path))
            logger.info(f"Wrote Picture UID {self.picture_uid} to {self.file_path}")
        
        # Update metadata
        self.metadata["picture_uid"] = self.picture_uid
        
        return self.picture_uid
    
    def get_pixel_array(self) -> np.ndarray:
        """Get pixel array from DICOM with robust first-try success.
        
        Pre-warms pixel handlers, retries with state reset, and uses a
        resilient approach ordering to avoid first-attempt failures.
        """
        if self._pixel_array is None:
            # Prewarm handlers before first attempt
            self._prewarm_dicom_reading()

            last_error = None
            max_attempts = 3  # Restore original attempts

            for attempt in range(1, max_attempts + 1):
                try:
                    logger.debug(f"Pixel read attempt {attempt} for {self.file_path.name}")

                    # Reorder approaches - put most reliable first
                    approaches = [
                        self._read_with_defer_size,
                        self._read_with_force,
                        self._read_with_specific_syntax,
                        self._read_with_decompression,
                        self._read_raw_pixels,
                        self._read_binary_parsing,
                        self._read_ultra_conservative,
                    ]

                    for i, approach in enumerate(approaches):
                        try:
                            logger.debug(f"Attempt {attempt}: approach {i+1} -> {approach.__name__}")
                            arr = approach()
                            if arr is not None and arr.size > 0:
                                self._pixel_array = arr
                                logger.info(f"Pixel data read on attempt {attempt} via {approach.__name__} for {self.file_path.name}")
                                return self._pixel_array
                        except Exception as e:
                            last_error = e
                            logger.debug(f"Approach {approach.__name__} failed on attempt {attempt}: {e}")
                            continue

                except Exception as e:
                    last_error = e
                    logger.debug(f"Pixel read attempt {attempt} raised: {e}")

                # Reset state before next attempt
                if attempt < max_attempts:
                    try:
                        self.dataset = None
                        self._pixel_array = None
                        import gc
                        gc.collect()
                    except Exception:
                        pass

            # If we get here, all attempts failed
            logger.error(f"All pixel reading attempts failed for {self.file_path.name}: {last_error}")
            raise Exception(f"All pixel reading attempts failed: {last_error}")

        return self._pixel_array
    
    
    def _read_ultra_conservative(self) -> np.ndarray:
        """Ultra-conservative read that bypasses problematic elements entirely"""
        import struct
        import numpy as np
        
        try:
            # First try: Handle JPEG Lossless and other compressed formats
            import pydicom.config
            from pydicom.pixel_data_handlers import pylibjpeg_handler, numpy_handler, pillow_handler
            
            # Configure handlers for compressed formats
            old_handlers = getattr(pydicom.config, 'pixel_data_handlers', [])
            old_enforce = getattr(pydicom.config, 'enforce_valid_values', True)
            old_convert = getattr(pydicom.config, 'convert_wrong_length_to_UN', False)
            
            try:
                # Set up handlers with pylibjpeg first for JPEG support
                handlers = []
                if JPEG_SUPPORT:
                    handlers.append(pylibjpeg_handler)
                handlers.extend([numpy_handler, pillow_handler])
                
                pydicom.config.pixel_data_handlers = handlers
                pydicom.config.enforce_valid_values = False
                pydicom.config.convert_wrong_length_to_UN = True
                
                # Try reading without defer_size first for compressed files
                ds = pydicom.dcmread(str(self.file_path), force=True)
                
                # Check if we have pixel data
                if hasattr(ds, 'pixel_array'):
                    self.dataset = ds
                    return ds.pixel_array
                elif hasattr(ds, 'PixelData') and ds.PixelData:
                    # Force pixel array creation
                    arr = ds.pixel_array
                    self.dataset = ds
                    return arr
                    
            finally:
                pydicom.config.pixel_data_handlers = old_handlers
                pydicom.config.enforce_valid_values = old_enforce
                pydicom.config.convert_wrong_length_to_UN = old_convert
        except Exception as e:
            logger.debug(f"JPEG Lossless approach failed: {e}")
            pass
        
        try:
            # Second try: Force decompression for compressed transfer syntaxes
            ds = pydicom.dcmread(str(self.file_path), force=True)
            
            # Check transfer syntax and handle accordingly
            transfer_syntax = getattr(ds.file_meta, 'TransferSyntaxUID', None)
            if transfer_syntax:
                logger.debug(f"Transfer syntax: {transfer_syntax}")
                
                # For JPEG Lossless (1.2.840.10008.1.2.4.70) and other compressed formats
                if '1.2.840.10008.1.2.4' in str(transfer_syntax):
                    # Try explicit decompression
                    if hasattr(ds, 'decompress'):
                        try:
                            ds.decompress()
                            logger.debug("Successfully decompressed DICOM")
                        except Exception as e:
                            logger.debug(f"Decompression failed: {e}")
            
            # Try to access pixel array
            if hasattr(ds, 'pixel_array'):
                self.dataset = ds
                return ds.pixel_array
            elif hasattr(ds, 'PixelData') and ds.PixelData:
                # Manual pixel array creation for problematic files
                rows = getattr(ds, 'Rows', 0)
                cols = getattr(ds, 'Columns', 0) 
                bits = getattr(ds, 'BitsAllocated', 8)
                samples = getattr(ds, 'SamplesPerPixel', 1)
                
                if rows > 0 and cols > 0:
                    import numpy as np
                    dtype = np.uint16 if bits == 16 else np.uint8
                    expected_size = rows * cols * samples * (bits // 8)
                    
                    if len(ds.PixelData) >= expected_size:
                        pixel_array = np.frombuffer(ds.PixelData[:expected_size], dtype=dtype)
                        if samples == 1:
                            pixel_array = pixel_array.reshape(rows, cols)
                        else:
                            pixel_array = pixel_array.reshape(rows, cols, samples)
                        
                        self.dataset = ds
                        return pixel_array
                        
        except Exception as e:
            logger.debug(f"Decompression approach failed: {e}")
            pass
        
        try:
            # Third try: Use gdcm or other decompression libraries if available
            try:
                import gdcm
                # Try GDCM-based decompression
                reader = gdcm.ImageReader()
                reader.SetFileName(str(self.file_path))
                if reader.Read():
                    image = reader.GetImage()
                    # Extract pixel data using GDCM
                    buffer_length = image.GetBufferLength()
                    if buffer_length > 0:
                        import numpy as np
                        buffer = bytearray(buffer_length)
                        image.GetBuffer(buffer)
                        
                        # Get image dimensions
                        dims = image.GetDimensions()
                        rows, cols = dims[1], dims[0]
                        
                        # Convert to numpy array
                        pixel_array = np.frombuffer(buffer, dtype=np.uint8)
                        pixel_array = pixel_array.reshape(rows, cols, -1)
                        
                        # Read metadata separately
                        self.dataset = pydicom.dcmread(str(self.file_path), stop_before_pixels=True, force=True)
                        return pixel_array
            except ImportError:
                pass
            except Exception as e:
                logger.debug(f"GDCM approach failed: {e}")
                
            # Fallback: Use specific_tags to only read pixel data
            ds = pydicom.dcmread(str(self.file_path), force=True, specific_tags=[(0x7fe0, 0x0010)])
            if hasattr(ds, 'PixelData') and ds.PixelData:
                # Read metadata separately
                meta_ds = pydicom.dcmread(str(self.file_path), stop_before_pixels=True, force=True)
                # Copy essential attributes
                for attr in ['Rows', 'Columns', 'BitsAllocated', 'SamplesPerPixel', 'PhotometricInterpretation']:
                    if hasattr(meta_ds, attr):
                        setattr(ds, attr, getattr(meta_ds, attr))
                self.dataset = ds
                return ds.pixel_array
        except Exception as e:
            logger.debug(f"Specific tags approach failed: {e}")
            pass
        
        # Last resort: Manual binary parsing
        try:
            with open(str(self.file_path), 'rb') as f:
                # Skip DICOM preamble (128 bytes) and DICM prefix (4 bytes)
                f.seek(132)
                
                # Look for pixel data tag (7FE0,0010) manually
                pixel_data = None
                rows, cols, bits_allocated, samples_per_pixel = None, None, None, None
                photometric = None
                
                # Get file size first
                f.seek(0, 2)
                file_size = f.tell()
                f.seek(132)  # Reset to after preamble
                
                # Read through file looking for key tags
                while f.tell() < file_size - 8:  # Leave some buffer
                    current_pos = f.tell()
                    
                    try:
                        # Read tag (4 bytes)
                        tag_bytes = f.read(4)
                        if len(tag_bytes) < 4:
                            break
                        
                        group, element = struct.unpack('<HH', tag_bytes)
                        tag = (group, element)
                        
                        # Try to determine if this is implicit or explicit VR
                        # Read next 2 bytes to check if they look like VR
                        vr_bytes = f.read(2)
                        if len(vr_bytes) < 2:
                            break
                        
                        # Check if this looks like a VR (two ASCII letters)
                        try:
                            vr = vr_bytes.decode('ascii')
                            if vr.isalpha() and len(vr) == 2:
                                # Explicit VR
                                if vr in ['OB', 'OW', 'OF', 'SQ', 'UT', 'UN']:
                                    f.read(2)  # Skip reserved bytes
                                    length_bytes = f.read(4)
                                    if len(length_bytes) < 4:
                                        break
                                    length = struct.unpack('<I', length_bytes)[0]
                                else:
                                    length_bytes = f.read(2)
                                    if len(length_bytes) < 2:
                                        break
                                    length = struct.unpack('<H', length_bytes)[0]
                            else:
                                # Implicit VR - the 2 bytes we read are part of length
                                f.seek(-2, 1)  # Go back
                                length_bytes = f.read(4)
                                if len(length_bytes) < 4:
                                    break
                                length = struct.unpack('<I', length_bytes)[0]
                        except:
                            # Assume implicit VR
                            f.seek(-2, 1)  # Go back
                            length_bytes = f.read(4)
                            if len(length_bytes) < 4:
                                break
                            length = struct.unpack('<I', length_bytes)[0]
                        
                        # Skip undefined length
                        if length == 0xFFFFFFFF:
                            # Try to find next tag
                            f.seek(8, 1)
                            continue
                        
                        # Check for important tags
                        if tag == (0x0028, 0x0010):  # Rows
                            if length == 2:
                                rows = struct.unpack('<H', f.read(2))[0]
                            else:
                                f.seek(length, 1)
                        elif tag == (0x0028, 0x0011):  # Columns
                            if length == 2:
                                cols = struct.unpack('<H', f.read(2))[0]
                            else:
                                f.seek(length, 1)
                        elif tag == (0x0028, 0x0100):  # Bits Allocated
                            if length == 2:
                                bits_allocated = struct.unpack('<H', f.read(2))[0]
                            else:
                                f.seek(length, 1)
                        elif tag == (0x0028, 0x0002):  # Samples Per Pixel
                            if length == 2:
                                samples_per_pixel = struct.unpack('<H', f.read(2))[0]
                            else:
                                f.seek(length, 1)
                        elif tag == (0x7FE0, 0x0010):  # Pixel Data
                            if length > 0 and length < 100 * 1024 * 1024:  # Reasonable size check
                                pixel_data = f.read(length)
                            break
                        else:
                            # Skip this element
                            if length > 0 and length < 100 * 1024 * 1024:  # Safety check
                                f.seek(length, 1)
                            else:
                                break
                                
                    except Exception as e:
                        logger.debug(f"Error during manual parsing at position {current_pos}: {e}")
                        # Try to advance to next potential tag
                        f.seek(current_pos + 8, 0)
                        continue
                
                # Try to construct pixel array from raw data
                if pixel_data and rows and cols:
                    try:
                        bits_allocated = bits_allocated or 16
                        samples_per_pixel = samples_per_pixel or 1
                        
                        dtype = np.uint16 if bits_allocated == 16 else np.uint8
                        expected_size = rows * cols * samples_per_pixel * (bits_allocated // 8)
                        
                        if len(pixel_data) >= expected_size:
                            pixel_array = np.frombuffer(pixel_data[:expected_size], dtype=dtype)
                            if samples_per_pixel == 1:
                                pixel_array = pixel_array.reshape(rows, cols)
                            else:
                                pixel_array = pixel_array.reshape(rows, cols, samples_per_pixel)
                            
                            # Try to read basic metadata for self.dataset
                            try:
                                self.dataset = pydicom.dcmread(str(self.file_path), stop_before_pixels=True, force=True, defer_size=1024)
                            except:
                                pass
                            
                            return pixel_array
                    except Exception as e:
                        logger.debug(f"Failed to construct pixel array: {e}")
        
        except Exception as e:
            logger.debug(f"Manual parsing failed: {e}")
        
        raise Exception("Could not extract pixel data with ultra-conservative approach")
    
    def _read_binary_parsing(self) -> np.ndarray:
        """Binary parsing approach using pydicom with maximum error tolerance"""
        import pydicom.config
        
        # Configure pydicom for maximum error tolerance
        old_enforce_valid_values = getattr(pydicom.config, 'enforce_valid_values', True)
        old_convert_wrong_length_to_UN = getattr(pydicom.config, 'convert_wrong_length_to_UN', False)
        
        try:
            pydicom.config.enforce_valid_values = False
            pydicom.config.convert_wrong_length_to_UN = True
            
            # Try reading with maximum defer size to skip all problematic elements
            ds = pydicom.dcmread(str(self.file_path), force=True, defer_size=1)
            self.dataset = ds
            
            # Force pixel array access
            return ds.pixel_array
            
        finally:
            # Restore original settings
            pydicom.config.enforce_valid_values = old_enforce_valid_values
            pydicom.config.convert_wrong_length_to_UN = old_convert_wrong_length_to_UN
    
    def _read_with_error_bypass(self) -> np.ndarray:
        """Original multi-approach reading with error bypass"""
        approaches = [
            self._read_with_defer_size,
            self._read_with_specific_syntax,
            self._read_with_decompression,
            self._read_with_force,
            self._read_raw_pixels
        ]
        
        for i, approach in enumerate(approaches):
            try:
                self._pixel_array = approach()
                if self._pixel_array is not None:
                    return self._pixel_array
            except Exception as e:
                logger.debug(f"Error bypass approach {i+1} failed: {e}")
                continue
        
        raise Exception("All error bypass approaches failed")
    
    def _prewarm_dicom_reading(self):
        """Pre-warm DICOM reading to avoid first-try failures"""
        try:
            # Ensure global environment is initialized
            try:
                initialize_dicom_environment()
            except Exception:
                pass
            # Configure pixel data handlers proactively first using module objects
            import pydicom.config
            from pydicom.pixel_data_handlers import numpy_handler, pillow_handler
            handlers = []
            # Prefer pylibjpeg first if available
            if JPEG_SUPPORT:
                try:
                    from pydicom.pixel_data_handlers import pylibjpeg_handler
                    handlers.append(pylibjpeg_handler)
                except Exception:
                    pass
            handlers.extend([numpy_handler, pillow_handler])

            # Only set once per process
            if getattr(pydicom.config, '_handlers_configured', False) is not True:
                pydicom.config.pixel_data_handlers = handlers
                pydicom.config._handlers_configured = True
            
            # Try multiple pre-warming approaches
            try:
                # Quick header read to initialize pydicom state
                temp_ds = pydicom.dcmread(str(self.file_path), stop_before_pixels=True, force=True)
                del temp_ds
            except:
                pass
                
            try:
                # Try defer_size pre-read
                temp_ds = pydicom.dcmread(str(self.file_path), defer_size=1024, stop_before_pixels=True, force=True)
                del temp_ds
            except:
                pass
                
        except Exception:
            pass  # Pre-warming is optional
    
    def _read_with_defer_size(self) -> np.ndarray:
        """Try reading with defer_size to handle large elements"""
        # Try progressively larger defer sizes
        defer_sizes = [1024, 10 * 1024, 100 * 1024, 1024 * 1024]
        
        for defer_size in defer_sizes:
            try:
                logger.debug(f"Trying defer_size={defer_size} for {self.file_path.name}")
                ds = pydicom.dcmread(str(self.file_path), force=True, defer_size=defer_size)
                self.dataset = ds
                self._ensure_transfer_syntax(ds)
                return ds.pixel_array
            except Exception as e:
                logger.debug(f"defer_size={defer_size} failed: {e}")
                continue
        
        # If all defer sizes fail, try without defer_size
        ds = pydicom.dcmread(str(self.file_path), force=True)
        self.dataset = ds
        self._ensure_transfer_syntax(ds)
        return ds.pixel_array
    
    def _read_raw_pixels(self) -> np.ndarray:
        """Last resort: try to extract pixel data directly"""
        import pydicom.filereader
        
        # Try multiple raw reading approaches
        approaches = [
            # Approach 1: File handle with force
            lambda: self._read_with_file_handle(),
            # Approach 2: Specific byte reading
            lambda: self._read_with_specific_tags(),
            # Approach 3: Skip problematic elements
            lambda: self._read_skip_large_elements()
        ]
        
        for i, approach in enumerate(approaches):
            try:
                logger.debug(f"Raw pixel approach {i+1} for {self.file_path.name}")
                return approach()
            except Exception as e:
                logger.debug(f"Raw pixel approach {i+1} failed: {e}")
                continue
        
        raise Exception("All raw pixel reading approaches failed")
    
    def _read_with_file_handle(self) -> np.ndarray:
        """Read using file handle approach"""
        with open(str(self.file_path), 'rb') as fp:
            ds = pydicom.filereader.dcmread(fp, force=True, stop_before_pixels=False)
        
        if hasattr(ds, 'PixelData') and ds.PixelData:
            self.dataset = ds
            self._ensure_transfer_syntax(ds)
            return ds.pixel_array
        else:
            raise Exception("No pixel data found")
    
    def _read_with_specific_tags(self) -> np.ndarray:
        """Read by avoiding problematic tags"""
        # Read with specific_tags to avoid problematic elements
        ds = pydicom.dcmread(str(self.file_path), force=True, specific_tags=[(0x7fe0, 0x0010)])  # PixelData tag
        
        if hasattr(ds, 'PixelData'):
            # Now read full dataset but with defer for large elements
            full_ds = pydicom.dcmread(str(self.file_path), force=True, defer_size=10 * 1024)
            # Copy pixel data
            full_ds.PixelData = ds.PixelData
            self.dataset = full_ds
            self._ensure_transfer_syntax(full_ds)
            return full_ds.pixel_array
        else:
            raise Exception("No pixel data found with specific tags")
    
    def _read_skip_large_elements(self) -> np.ndarray:
        """Read while skipping large elements that cause offset errors"""
        # Use a very small defer size to skip large problematic elements
        ds = pydicom.dcmread(str(self.file_path), force=True, defer_size=256)
        self.dataset = ds
        self._ensure_transfer_syntax(ds)
        
        # Try to access pixel array with error handling
        try:
            return ds.pixel_array
        except Exception:
            # If pixel array access fails, try to reconstruct it
            if hasattr(ds, 'PixelData') and ds.PixelData:
                # Force pixel array creation
                import numpy as np
                # This is a fallback - may not work for all cases
                pixel_bytes = ds.PixelData
                if len(pixel_bytes) > 0:
                    # Try to interpret as raw pixel data
                    rows = getattr(ds, 'Rows', 512)
                    cols = getattr(ds, 'Columns', 512)
                    samples = getattr(ds, 'SamplesPerPixel', 1)
                    bits = getattr(ds, 'BitsAllocated', 16)
                    
                    dtype = np.uint16 if bits == 16 else np.uint8
                    expected_size = rows * cols * samples * (bits // 8)
                    
                    if len(pixel_bytes) >= expected_size:
                        pixel_array = np.frombuffer(pixel_bytes[:expected_size], dtype=dtype)
                        if samples == 1:
                            pixel_array = pixel_array.reshape(rows, cols)
                        else:
                            pixel_array = pixel_array.reshape(rows, cols, samples)
                        return pixel_array
            
            raise Exception("Could not reconstruct pixel array")
    
    def _read_with_force(self) -> np.ndarray:
        """Try reading with force=True"""
        # Always read fresh to avoid state issues
        self.dataset = pydicom.dcmread(str(self.file_path), force=True)
        self._ensure_transfer_syntax(self.dataset)
        return self.dataset.pixel_array
    
    def _read_with_decompression(self) -> np.ndarray:
        """Try reading with explicit decompression"""
        # Read fresh dataset
        ds = pydicom.dcmread(str(self.file_path), force=True)
        
        # Try to decompress if method exists
        if hasattr(ds, 'decompress'):
            try:
                ds.decompress()
                logger.debug(f"Successfully decompressed {self.file_path.name}")
            except Exception as e:
                logger.debug(f"Decompression failed for {self.file_path.name}: {e}")
                # Continue anyway, sometimes pixel_array works even if decompress fails
        
        self.dataset = ds
        self._ensure_transfer_syntax(ds)
        return ds.pixel_array
    
    def _read_with_specific_syntax(self) -> np.ndarray:
        """Try reading with specific transfer syntax handling and error bypass"""
        import pydicom.config
        from pydicom.errors import InvalidDicomError
        
        # Enable decompression handlers
        try:
            from pydicom.pixel_data_handlers import numpy_handler, pillow_handler
            handlers = []
            if JPEG_SUPPORT:
                try:
                    from pydicom.pixel_data_handlers import pylibjpeg_handler
                    handlers.append(pylibjpeg_handler)
                except Exception:
                    pass
            handlers.extend([numpy_handler, pillow_handler])
            pydicom.config.pixel_data_handlers = handlers
        except Exception:
            # If handler configuration fails, proceed with whatever is available
            pass
        
        # Try with different reading strategies for problematic files
        try:
            # First attempt: normal read
            ds = pydicom.dcmread(str(self.file_path), force=True)
        except Exception as e:
            if "Element offset must be less than 256" in str(e):
                # Try reading with defer_size set to handle large elements
                try:
                    ds = pydicom.dcmread(str(self.file_path), force=True, defer_size=1024)
                except Exception:
                    # Last resort: read with specific_tags to bypass problematic elements
                    ds = pydicom.dcmread(str(self.file_path), force=True, specific_tags=None)
            else:
                raise e
        
        # Handle missing transfer syntax
        if not hasattr(ds.file_meta, 'TransferSyntaxUID'):
            ds.file_meta.TransferSyntaxUID = ImplicitVRLittleEndian
        
        # Try to decompress if available
        if hasattr(ds, 'decompress'):
            try:
                ds.decompress()
            except Exception:
                pass  # Continue even if decompression fails
        
        self.dataset = ds
        return ds.pixel_array
    
    def export_image(self, output_path: Path, format: str = "TIFF") -> Path:
        """Export image to file"""
        pixel_array = self.get_pixel_array()
        
        # Convert to PIL Image
        if len(pixel_array.shape) == 3:
            # RGB image
            image = Image.fromarray(pixel_array)
        else:
            # Grayscale
            # Normalize if needed
            if pixel_array.dtype != np.uint8:
                # Scale to 0-255
                min_val = pixel_array.min()
                max_val = pixel_array.max()
                if max_val > min_val:
                    pixel_array = ((pixel_array - min_val) * 255 / (max_val - min_val)).astype(np.uint8)
                else:
                    pixel_array = np.zeros_like(pixel_array, dtype=np.uint8)
            image = Image.fromarray(pixel_array, mode='L')
        
        # Save image
        image.save(output_path, format=format)
        return output_path
    
    def get_metadata_for_export(self, deidentify: bool = False) -> Dict[str, Any]:
        """Get metadata dict for export"""
        export_data = self.metadata.copy()
        
        # Ensure Picture UID is included
        if self.picture_uid:
            export_data["picture_uid"] = self.picture_uid
        
        if deidentify:
            # Remove PHI fields
            for field in PHI_FIELDS:
                export_data.pop(field, None)
            export_data["deidentified"] = True
        
        return export_data
    
class DicomDirectory:
    """Manager for a directory of DICOM files"""
    
    def __init__(self, directory_path: Path):
        self.directory_path = directory_path
        self.dicom_files: List[DicomFile] = []
        self._scan_directory()
    
    def _scan_directory(self):
        """Scan directory for DICOM files"""
        dcm_paths = []
        
        # Look for .dcm files
        for path in self.directory_path.rglob("*.dcm"):
            if path.is_file():
                dcm_paths.append(path)
        
        # Also check files without extension
        for path in self.directory_path.rglob("*"):
            if path.is_file() and path.suffix == "":
                # Try to detect if it's DICOM
                try:
                    with open(path, 'rb') as f:
                        f.seek(128)
                        if f.read(4) == b'DICM':
                            dcm_paths.append(path)
                except Exception:
                    pass
        
        # Load DICOM files
        for path in sorted(dcm_paths):
            try:
                dicom_file = DicomFile(path)
                self.dicom_files.append(dicom_file)
                logger.info(f"Loaded DICOM: {path}")
            except Exception as e:
                logger.warning(f"Failed to load {path}: {e}")
    
    def get_file_count(self) -> int:
        """Get number of DICOM files"""
        return len(self.dicom_files)
    
    def get_file_list(self) -> List[str]:
        """Get list of file names"""
        return [f.file_path.name for f in self.dicom_files]
    
    def get_file_by_index(self, index: int) -> Optional[DicomFile]:
        """Get DICOM file by index"""
        if 0 <= index < len(self.dicom_files):
            return self.dicom_files[index]
        return None
    
    def get_file_by_name(self, name: str) -> Optional[DicomFile]:
        """Get DICOM file by name"""
        for f in self.dicom_files:
            if f.file_path.name == name:
                return f
        return None
