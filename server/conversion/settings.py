import os

# 1. Start with Localhost as the base
# DICOMWEB_URL: str = "http://localhost:8080/dicom-web"
# ABPAPI_URL: str = "https://localhost:44373/api/volview"
DICOMWEB_URL: str = "https://dicom-pacs-int.smartsurgerytek.net/dicom-web"  
ABPAPI_URL: str = "https://dicom-api-int.smartsurgerytek.net/api/volview" 

print("DEBUG DICOMWEB_URL =", DICOMWEB_URL)
print("DEBUG ABPAPI_URL =", ABPAPI_URL)