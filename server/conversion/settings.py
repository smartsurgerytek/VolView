import os

# 1. Base Defaults
DEFAULT_DICOM = "http://localhost:8080/dicom-web"
DEFAULT_ABP = "https://localhost:44373/api/volview"

# 2. Force read from Environment Variables (set in Cloud Run/GitHub Actions)
# If the variable exists, it uses it. If not, it uses the default.
DICOMWEB_URL = os.getenv("DICOMWEB_URL", DEFAULT_DICOM)
ABPAPI_URL = os.getenv("ABPAPI_URL", DEFAULT_ABP)

python_env = os.getenv("PYTHON_ENV", "development")
print(f"DEBUG: PYTHON_ENV is: {python_env}")

# 3. Optional: Still keep your file logic if you want, but clean it up
if python_env == "Integration" and DICOMWEB_URL == DEFAULT_DICOM:
    try:
        # Change to a standard import
        import settings_integration
        DICOMWEB_URL = settings_integration.DICOMWEB_URL
        ABPAPI_URL = settings_integration.ABPAPI_URL
        print("DEBUG: Loaded from settings_integration.py")
    except ImportError:
        print("DEBUG: settings_integration.py not found, using Environment/Defaults")

print(f"DEBUG: Final DICOMWEB_URL: {DICOMWEB_URL}")
print(f"DEBUG: Final ABPAPI_URL: {ABPAPI_URL}")