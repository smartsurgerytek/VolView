import os

# Default Localhost URLs
DICOMWEB_URL: str = "http://localhost:8080/dicom-web"
ABPAPI_URL: str = "https://localhost:44373/api/volview"

# Check if we should use Integration settings
if os.getenv("PYTHON_ENV") == "Integration":
    try:
        from .settings_Integration import DICOMWEB_URL as CLOUD_DICOM, ABPAPI_URL as CLOUD_ABP
        DICOMWEB_URL = CLOUD_DICOM
        ABPAPI_URL = CLOUD_ABP
        print("Running with Integration Settings")
    except ImportError:
        print("Integration settings file not found, using defaults")