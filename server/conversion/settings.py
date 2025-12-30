import os

# Localhost Defaults
DICOMWEB_URL = "http://localhost:8080/dicom-web"
ABPAPI_URL = "https://localhost:44373/api/volview"

python_env = os.getenv("PYTHON_ENV")
print(f"DEBUG: PYTHON_ENV is set to: {python_env}")

if python_env == "Integration":
    try:
        from .settings_integration import DICOMWEB_URL as CLOUD_DICOM, ABPAPI_URL as CLOUD_ABP
        DICOMWEB_URL = CLOUD_DICOM
        ABPAPI_URL = CLOUD_ABP
        print("DEBUG: Successfully loaded Integration settings")
    except Exception as e:
        print(f"DEBUG: Failed to load integration settings. Error: {e}")