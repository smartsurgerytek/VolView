import os

# 1. Start with Localhost as the base
DICOMWEB_URL: str = "http://localhost:8080/dicom-web"
ABPAPI_URL: str = "https://localhost:44373/api/volview"

python_env = os.getenv("PYTHON_ENV")
print(f"DEBUG: PYTHON_ENV is set to: {python_env}")

# 2. If Integration, TRY to overwrite them
if python_env == "Integration":
    try:
        # Import the cloud variables from your new file
        from .settings_integration import DICOMWEB_URL as CLOUD_DICOM, ABPAPI_URL as CLOUD_ABP
        
        # ASSIGN the cloud values to the main variables
        DICOMWEB_URL = CLOUD_DICOM
        ABPAPI_URL = CLOUD_ABP
        
        print(f"DEBUG: Successfully loaded Integration settings. DICOM URL is now: {DICOMWEB_URL}")
    except ImportError as e:
        print(f"DEBUG: Integration settings file not found. Error: {e}")
    except Exception as e:
        print(f"DEBUG: An error occurred while switching settings: {e}")

# 3. Final verification print
print(f"DEBUG: Final DICOMWEB_URL being used: {DICOMWEB_URL}")