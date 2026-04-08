import gzip
import os
import requests
from pathlib import Path
from typing import Dict
from fastapi import Depends, FastAPI, Request, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

import httpx
import hashlib
import zipfile
import json
import io
import pydicom
from pydicom.uid import generate_uid

import numpy as np
import pydicom
from PIL import Image
import base64

from models import Manifest
# from conversion import settings
import settings
from sr_generator import SRGenerator
import vtk # 匯入 vtk
from vtk.util import numpy_support

from datetime import datetime
from utils1 import (
    DotDict,
    get_filepath_for_subject,
    read_file_from_zip,
    create_empty_sr,
    update_general_module,
    update_patient_module,
    update_sr_content_module,
    update_private_tags
)

from utils2 import (
    Rulers,
    Dentals,
    Tools,
    Layout,
    ViewerSession,
    generate_data_structure,
    create_volview_zip_from_memory
)

from dicomweb_client.api import DICOMwebClient

from fastapi import FastAPI, UploadFile, Form
from fastapi.responses import FileResponse
from pathlib import Path
import subprocess
import json

dicomweb_url = settings.DICOMWEB_URL

# Set this to 'integration' in your Cloud Run settings
# Locally, it will default to 'development'



client = DICOMwebClient(
url=dicomweb_url
)


# env_type = os.getenv("ENV_TYPE", "development")
# print(f"Environment Type: {env_type}")
# if env_type == "development":
#     client = DICOMwebClient(
#         url=dicomweb_url
#     )
# else:
#     # Integration/Production: No defaults, force system to use real secrets
#     orthanc_user = os.getenv("ORTHANC_USERNAME")
#     orthanc_pass = os.getenv("ORTHANC_PASSWORD")
    
#     if not orthanc_user or not orthanc_pass:
#         raise ValueError("ORTHANC_USERNAME and ORTHANC_PASSWORD must be set in the environment for production/integration environments.")
    
#     session = requests.Session()
#     session.auth = (orthanc_user, orthanc_pass)
#     client = DICOMwebClient(
#         url=dicomweb_url,
#         session=session
#     )

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    app.state.http_client = httpx.AsyncClient(verify=False)

@app.on_event("shutdown")
async def shutdown_event():
    await app.state.http_client.aclose()

@app.post("/api/save")  
async def save_session_to_sr_and_seg(request: Request):
    try:
        print("Received /api/save request")
        zip_data = await request.body()

        print(f"Zip data size: {len(zip_data)} bytes")

        if not zip_data:
            raise ValueError("No zip data received in the request body")

        # get manifest
        zip_file_in_memory = io.BytesIO(zip_data)
        manifest_string = read_file_from_zip(zip_file_in_memory, "manifest.json")
        manifest = DotDict.from_dict(json.loads(manifest_string))
        print("Successfully read manifest.json from zip")

        # get any subject dicom file to get study_instance_uid
        study_instance_uid = ''

        path_value = list(manifest['datasetFilePath'].values())[0]
        subject = read_file_from_zip(zip_file_in_memory,path_value)

        ds = pydicom.dcmread(io.BytesIO(subject))
        study_instance_uid = ds.get('StudyInstanceUID')
        patient_id = ds.get('PatientID')

        subjects = []
        measurements = []

        for dataset in manifest['datasets']:
            subjects.append(dataset)

        for ruler in manifest['tools']['rulers']['tools']:
            measurements.append(ruler)

        sr_index = 1

        # Check is Existing Series(series description = Measurement Report) in the study
        series_instance_UID = await get_series_uid()

        # delete the Series (series description = Measurement Report) before creating new
        delete_response = await delete_orthanc_series(patient_id, study_instance_uid, series_instance_UID)

        print("delete_response:", delete_response)

        for subject in subjects:
            filepath = get_filepath_for_subject(subject, manifest)
            print('filepath:', filepath)

            subject_ds = pydicom.dcmread(io.BytesIO(read_file_from_zip(zip_file_in_memory, filepath)))

            for measurement in measurements:
                if subject['id'] != measurement['imageID']:
                    continue

                # get measurement data
                print('start process measurement id:',measurement['id'])
                print(measurement)

                # Create SR file
                sr_ds = create_empty_sr()
                sr_ds = update_general_module(sr_ds, subject_ds)
                sr_ds = update_patient_module(sr_ds, subject_ds)
                sr_ds = update_private_tags(sr_ds, measurement)

                sr_ds.SeriesInstanceUID = series_instance_UID

                # Save
                # enforce_file_format will automatically caculate the (0002,0000) File Meta Information Group Length
                response = client.store_instances(datasets=[sr_ds])

                sr_index +=1

            print('--------------------------')

        return JSONResponse(
                content={'success': True},  
                status_code=200
            )

    except Exception as e:  
        print(f"Error saving session: {e}")  
        return JSONResponse(  
            content={'success': False, 'error': str(e)},  
            status_code=500  
        )

@app.post("/api/load")
async def load_session(request: Request):
    try:
        print("Received /api/load request")

        study_instance_uid = (await request.json()).get('StudyInstanceUID')

        # Validate input : StudyInstanceUID
        if not study_instance_uid:
            raise ValueError("StudyInstanceUID is required in the request body")

        print(f"StudyInstanceUID: {study_instance_uid}")

        # Get all instances in the study
        instances = client.search_for_instances(
            study_instance_uid=study_instance_uid
        )

        if len(instances) == 0:
            raise ValueError(f"No instances found for StudyInstanceUID: {study_instance_uid}")

        print(f"Found {len(instances)} instances in the study.")
        dataset_uids = []
        subject_files = {}

        for instance in instances:
            ds = client.retrieve_instance(
                study_instance_uid=instance.get('0020000D')['Value'][0],
                series_instance_uid=instance.get('0020000E')['Value'][0],
                sop_instance_uid=instance.get('00080018')['Value'][0],
            )

            # simulate datasetid (use SOPInstanceUID to guarantee uniqueness per instance)
            datasetId = f"{ds.get('SOPInstanceUID')}.1{ds.get('Rows')}{ds.get('Columns')}{ds.get('SeriesDate')}.1D000000S0D000000S0D000000S0D000000S1D000000S0D000000"
            dataset_uids.append(datasetId)

            subject_filename = f"{ds.get('PatientID')}-{ds.get('StudyDate')}-{ds.get('InstanceNumber')}.dcm"
            subject_files[subject_filename] = [ds.get('SOPInstanceUID'), ds.get('SeriesInstanceUID'), ds.get('StudyInstanceUID')]
            print('subject_files:', subject_files)

        generated_datasets, generated_sources, generated_paths = generate_data_structure(dataset_uids, subject_files)

        viewer_session = ViewerSession(
                version="5.0.1",
                datasets=generated_datasets,
                dataSources=generated_sources,
                datasetFilePath=generated_paths,
                labelMaps=[],
                tools=Tools(
                    crosshairs={"position": (0, 0, 0)},
                    paint={"activeSegmentGroupID": None, "activeSegment": 1, "brushSize": 4},
                    crop={},
                    current="Ruler",
                    polygons={"tools": [], "labels": {}},
                    rectangles={"tools": [], "labels": {}},
                    rulers=Rulers(tools=[], labels={}),
                    dental=Dentals(tools=[], labels={}),
                    ),
                layout=Layout(name="Axial Only", direction="H", items=["Axial"]),
                views=[],
                parentToLayers=[],
                primarySelection=dataset_uids[-1]
            )
        # Save
        session_zip_bytes = await create_volview_zip_from_memory(
            viewer_session=viewer_session,
            generated_paths=generated_paths,
            subject_files=subject_files,
            client=client)

        print(f"Session ZIP size: {len(session_zip_bytes)} bytes")

        return Response(content=session_zip_bytes, media_type="application/zip")

    except Exception as e:
        print(f"Error loading session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/load_with_anno")
async def load_session_with_anno(request: Request):
    try:
        print("Received /api/load_with_anno request")
        apiClient: httpx.AsyncClient = app.state.http_client
        study_instance_uid = (await request.json()).get('StudyInstanceUID')

        # Validate input : StudyInstanceUID
        if not study_instance_uid:
            raise ValueError("StudyInstanceUID is required in the request body")

        print(f"StudyInstanceUID: {study_instance_uid}")

        # Get all instances in the study
        instances = client.search_for_instances(
            study_instance_uid=study_instance_uid
        )

        if len(instances) == 0:
            raise ValueError(f"No instances found for StudyInstanceUID: {study_instance_uid}")

        print(f"Found {len(instances)} instances in the study.")
        dataset_uids = []
        subject_files = {}
        measurement_data = []

        # Try to fetch stored manifest from C# DB directly (independent of SR detection,
        # since the SR is created asynchronously and may not be in PACS yet when user reloads)
        viewer_session = None
        try:
            abpapi_url = f"{settings.ABPAPI_URL}/manifest/{study_instance_uid}"
            manifest_response = await apiClient.get(str(abpapi_url))
            manifest_response.raise_for_status()
            manifest_text = manifest_response.text
            if manifest_text and manifest_text.strip():
                viewer_session = ViewerSession(**manifest_response.json())
                print("Stored manifest found in C# DB.")
        except Exception as e:
            print(f"No stored manifest found in C# DB (or parse error): {e}")
            viewer_session = None

        for instance in instances:
            ds = client.retrieve_instance(
                study_instance_uid=instance.get('0020000D')['Value'][0],
                series_instance_uid=instance.get('0020000E')['Value'][0],
                sop_instance_uid=instance.get('00080018')['Value'][0],
            )

            # simulate datasetid (use SOPInstanceUID to guarantee uniqueness per instance)
            if((ds.get('Modality') != 'SR') and (ds.get('Modality') != 'SEG')):
                print("Image Instance Found")
                datasetId = f"{ds.get('SOPInstanceUID')}.1{ds.get('Rows')}{ds.get('Columns')}{ds.get('SeriesDate')}.1D000000S0D000000S0D000000S0D000000S1D000000S0D000000"
                dataset_uids.append(datasetId)

                subject_filename = f"{ds.get('PatientID')}-{ds.get('StudyDate')}-{ds.get('InstanceNumber')}.dcm"
                subject_files[subject_filename] = [ds.get('SOPInstanceUID'), ds.get('SeriesInstanceUID'), ds.get('StudyInstanceUID')]

        generated_datasets, generated_sources, generated_paths = generate_data_structure(dataset_uids, subject_files)

        # if stored manifest found: update only the file paths in datasetFilePath.
        # Keep datasets/dataSources intact — their IDs are ITK-wasm computed and must
        # match the imageID values stored in rulers/labelMaps.
        if viewer_session is not None:
            # Build sopInstanceUID → generated path mapping
            sop_to_path: Dict[str, str] = {}
            for path in generated_paths.values():
                filename = path.split('/')[-1]
                sop_uid = subject_files[filename][0]
                sop_to_path[sop_uid] = path

            # Build dataSource lookup by id
            datasource_map = {src.id: src for src in viewer_session.dataSources}

            # For each stored dataset, find its SOPInstanceUID via prefix match,
            # then walk dataset → collection → file dataSource to get fileId,
            # and update the path in datasetFilePath
            for dataset in viewer_session.datasets:
                for sop_uid, path in sop_to_path.items():
                    if dataset.id.startswith(sop_uid):
                        collection_src = datasource_map.get(dataset.dataSourceId)
                        if collection_src and collection_src.sources:
                            file_src = datasource_map.get(collection_src.sources[0])
                            if file_src and file_src.fileId is not None:
                                viewer_session.datasetFilePath[str(file_src.fileId)] = path
                        break

            is_manifest_from_sr = True

        # if no stored manifest found
        if viewer_session is None:
            print("No stored manifest found. Creating empty viewer session.")
            fake_layout = Layout(name="Axial Only", direction="H", items=["Axial"])
            fake_tools = Tools(
                crosshairs={"position": (0, 0, 0)},
                paint={"activeSegmentGroupID": None, "activeSegment": 1, "brushSize": 4},
                crop={},
                current="Ruler",
                polygons={"tools": [], "labels": {}},
                rectangles={"tools": [], "labels": {}},
                rulers=Rulers(tools=measurement_data, labels={}),
                dental=Dentals(tools=[], labels={}),
                )
            viewer_session = ViewerSession(
                version="5.0.1",
                datasets=generated_datasets,
                dataSources=generated_sources,
                datasetFilePath=generated_paths,
                labelMaps=[],
                tools=fake_tools,
                layout=fake_layout,
                views=[],
                parentToLayers=[],
                primarySelection=dataset_uids[-1]
            )
            is_manifest_from_sr = False

        # Save
        session_zip_bytes = await create_volview_zip_from_memory(
            viewer_session=viewer_session,
            generated_paths=generated_paths,
            subject_files=subject_files,
            client=client,
            is_manifest_from_sr=is_manifest_from_sr)

        print(f"Session ZIP size: {len(session_zip_bytes)} bytes")

        return Response(content=session_zip_bytes, media_type="application/zip")

    except Exception as e:
        print(f"Error loading session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def get_series_uid():
    series = client.search_for_series(search_filters={'SeriesDescription': 'Measurement Report'})
    if series:
        print("Existing Measurement Report series found in the study.")
        return series[0].get('0020000E')['Value'][0]
    else:
        print("No existing Measurement Report series found. A new series will be created.")
        return generate_uid()


ORTHANC_BASE_URL = os.getenv("DIRECT_ORTHANC_URL", "https://dicom-pacs-int.smartsurgerytek.net")

async def delete_orthanc_series(
    patient_id: str, 
    study_instance_uid: str, 
    series_instance_uid: str
) -> dict:
    """
    Send an asynchronous DELETE request to the Orthanc server to delete a specific Series.

    This function computes Orthanc's SHA-1 stable identifier using the provided
    PatientID, StudyInstanceUID, and SeriesInstanceUID before sending the request.

    Args:
        patient_id (str): Value of DICOM tag (0010,0020).
        study_instance_uid (str): Value of DICOM tag (0020,000D).
        series_instance_uid (str): Value of DICOM tag (0020,000E).

    Returns:
        dict: A dictionary containing the result of the DELETE request.
    """

    orthanc_id = None  # initialize first

    try:
        # --- 1. Calculate Orthanc SHA-1 ID ---
        # According to the rule: SHA-1(PatientID + StudyInstanceUID + SeriesInstanceUID)
        # Ensure the string concatenation order and content are exactly correct
        concatenated_string = f"{patient_id}|{study_instance_uid}|{series_instance_uid}"

        # Encode the string to bytes (SHA-1 must operate on bytes)
        concatenated_bytes = concatenated_string.encode('utf-8')
        sha1_hash_obj = hashlib.sha1(concatenated_bytes)
        raw_hash = sha1_hash_obj.hexdigest()
        parts = []
        for i in range(0, len(raw_hash), 8):
            parts.append(raw_hash[i:i+8])
        orthanc_id = "-".join(parts)
        # Create SHA-1 hash object
        # sha1_hash_obj = hashlib.sha1(concatenated_bytes)

        # Get the hexadecimal string (this is the Orthanc ID)
        # orthanc_id = sha1_hash_obj.hexdigest()
        # --- ------------------------ ---

        # 2. Build the full API URL (using the calculated hash ID)
        url = f"{ORTHANC_BASE_URL}/series/{orthanc_id}"

        # 3. Send the request
        async with httpx.AsyncClient() as client:
            print(f"--- Preparing to delete Series ---")
            print(f"PatientID: {patient_id}")
            print(f"StudyInstanceUID: {study_instance_uid}")
            print(f"SeriesInstanceUID: {series_instance_uid}")
            print(f"Calculated Orthanc ID (SHA-1): {orthanc_id}")
            print(f"Sending DELETE request to: {url}")

            response = await client.delete(url)

            # Check HTTP status code
            response.raise_for_status()

            # --- Request successful (2xx status code) ---
            try:
                # Try to parse JSON returned by Orthanc
                response_data = response.json()
            except json.JSONDecodeError:
                # If Orthanc returns empty content or plain text
                response_data = response.text

            print(f"Series deleted successfully (status code: {response.status_code})")
            return {
                "success": True,
                "status_code": response.status_code,
                "orthanc_id": orthanc_id,
                "data": response_data
            }

    except httpx.HTTPStatusError as e:
        # Handle HTTP errors (e.g. 404, 405, 500)
        print(f"HTTP error: {e.response.status_code} - {e.response.text}")
        return {
            "success": False,
            "status_code": e.response.status_code,
            "orthanc_id": orthanc_id,  # still return ID for debugging
            "error": "HTTP Error",
            "details": e.response.text
        }
    except httpx.RequestError as e:
        # Handle connection errors (e.g. connection refused)
        print(f"Connection error: {e}")
        return {
            "success": False,
            "status_code": None,
            "orthanc_id": orthanc_id,
            "error": "Connection Error",
            "details": str(e)
        }
    except Exception as e:
        # Catch other unexpected errors
        print(f"An unexpected error occurred: {e}")
        return {
            "success": False,
            "status_code": None,
            "orthanc_id": orthanc_id,
            "error": "Unexpected Error",
            "details": str(e)
        }

@app.post("/api/get_segmentation")
async def get_segmentation(request: Request):
    try:
        print("Received /api/get_segmentation request")

        

        study_instance_uid = (await request.json()).get('StudyInstanceUID')
        series_instance_uid = (await request.json()).get('SeriesInstanceUID')
        sop_instance_uid = (await request.json()).get('SopInstanceUID')



        if not study_instance_uid :
            raise ValueError("StudyInstanceUID is required in the request body")

        if not series_instance_uid :
            raise ValueError("SeriesInstanceUID is required in the request body")

        if not sop_instance_uid:
            raise ValueError("SopInstanceUID is required in the request body")


        print("===========================he=============Get Dicom Instance start===================================================")


        # Get Dicom Instance
        instance = client.retrieve_instance(
                study_instance_uid=study_instance_uid,
                series_instance_uid=series_instance_uid,
                sop_instance_uid=sop_instance_uid,
            )

        print("========================================Get Image base64 String===================================================")
        # Get Image base64 String
        instance_base64 = get_base64_string(instance)

        print("========================================invoke dentistry api===================================================")
        # invoke dentistry api
        segmentation_response = await get_dentistry_segmentation(instance_base64)

        if 'yolo_results' not in segmentation_response or 'yolov8_contents' not in segmentation_response['yolo_results']:
            raise ValueError("API response does not contain 'yolo_results.yolov8_contents'")

        # ##### TODO: only for testing
        # debug_filename = "debug_segmentation_response_output.txt"
        # with open(debug_filename, "w", encoding="utf-8") as f:
        #     json.dump(segmentation_response, f, indent=4, ensure_ascii=False)
        # print(f"--- debug_segmentation_response_output已儲存到 {debug_filename} 供除錯 ---")
        # #####


        print("========================================get_vti_file===================================================")
        vti_content_bytes = get_vti_file(instance,segmentation_response)

        return Response(
            content=vti_content_bytes,
            media_type="application/xml",
            headers={
                "Content-Disposition": f"attachment; filename=segmentation_{sop_instance_uid}.vti"
            }
        )

    except Exception as e:
        print(f"Error getting segmentation: {e}")
        raise HTTPException(status_code=500, detail=str(e))

print("========================================get_base64_string===================================================")

def get_base64_string(ds):
    new_image = ds.pixel_array.astype(float)
    print("Original image shape:", new_image.shape)

    # Rescaling the image
    scaled_image = (np.maximum(new_image, 0) / new_image.max()) * 255.0
    
    scaled_image = np.uint8(scaled_image)
    final_image = Image.fromarray(scaled_image)
    
    # save
    buffered = io.BytesIO()
    final_image.save(buffered, format="PNG")

    base64_string = base64.b64encode(buffered.getvalue()).decode('utf-8')
    return base64_string

    print("========================================get_dentistry_segmentation===================================================")

async def get_dentistry_segmentation(base64_string: str):

    url = "https://api-int.smartsurgerytek.net/v1/pa_segmentation_cvat"
    payload = {
            "image": base64_string
        }

    query_params = {
        "key": "apikey"
        }

    timeout_config = httpx.Timeout(30.0, connect=5.0)

    print("========================================invoke Inference API===================================================")

    async with httpx.AsyncClient(timeout=timeout_config) as client:
        try:
            print(f"--- ready to invoke Inference API: {url} ---")

            response = await client.post(
                url,
                json=payload,
                params=query_params
            )

            print("========================================response===================================================")

            response.raise_for_status()

            response_data = response.json()
            print(f"API response received successfully (status code: {response.status_code})")
            return response_data

        except httpx.HTTPStatusError as e:
            print(f"API request error: {e.response.status_code} - {e.response.text}")
        except httpx.RequestError as e:
            print(f"Network connection error: {e}")
            raise
        except json.JSONDecodeError:
            print(f"Unable to parse API response (non-JSON): {response.text}")
            raise

def get_vti_file(instance, segmentation_response):
    try:
        # 3. get metadata
        H, W = instance.Rows, instance.Columns

        ## after setting PixelSpacing=[1.0, 1.0], the brush works!
        pixel_spacing = instance.PixelSpacing if "PixelSpacing" in instance else [1.0, 1.0]
        slice_thickness = float(instance.SliceThickness if "SliceThickness" in instance else 1.0)
        origin = instance.ImagePositionPatient if "ImagePositionPatient" in instance else [0.0, 0.0, 0.0]

        # 4. create canvas
        # *** assumption: class ID range is 0-255 (uint8) ***
        final_mask = np.zeros((H, W), dtype=np.uint8)

        # 5. decode RLE and compose mask
        # *** assumption: API response structure matches your example ***
        # (you may need to adjust 'yolo_results' and 'yolov8_contents' based on your API response)
        if 'yolo_results' not in segmentation_response or 'yolov8_contents' not in segmentation_response['yolo_results']:
            raise ValueError("API response does not contain 'yolo_results.yolov8_contents'")
        
        class_names = segmentation_response['yolo_results']['class_names']
        class_name_to_class_id = {v: k for k, v in class_names.items()}
        
        yolov8_contents = segmentation_response['yolo_results']['yolov8_contents']

        print(f"Processing {len(yolov8_contents)} segmented objects...")

        for obj in yolov8_contents:
            points = obj.get('points')
            label = obj.get('label')
            class_id = int(class_name_to_class_id.get(label))

            if not points or class_id is None:
                print("Skipping invalid object with missing points or class_id")
                continue

            # 1. decode RLE
            bbox_mask, x1, y1, x2, y2 = rle2Mask(points)
            if bbox_mask.size == 0:
                print(f"Skipping empty mask for class {class_id}")
                continue

            # 2. find overlapping region between source (bbox_mask) and target (final_mask)

            # --- 2a. compute overlap region in global coordinates (relative to final_mask) ---
            # BBox x2, y2 are inclusive, so add +1 to the end index
            x_start_global = max(x1, 0)
            y_start_global = max(y1, 0)
            x_end_global = min(x2 + 1, W)  # W is the width of final_mask
            y_end_global = min(y2 + 1, H)  # H is the height of final_mask
            
            print(f"Class {class_id}: Global Overlap Region - X: [{x_start_global}, {x_end_global}), Y: [{y_start_global}, {y_end_global})")

            # --- 2b. if there is no overlap at all, skip ---
            if x_start_global >= x_end_global or y_start_global >= y_end_global:
                print(f"Skipping mask for class {class_id} (BBox completely out of bounds)")
                continue

            # --- 2c. compute overlap region in local coordinates (relative to bbox_mask) ---
            x_start_local = x_start_global - x1
            y_start_local = y_start_global - y1
            x_end_local = x_end_global - x1
            y_end_local = y_end_global - y1
            
            print(f"Class {class_id}: Local Overlap Region - X: [{x_start_local}, {x_end_local}), Y: [{y_start_local}, {y_end_local})")

            # 3. based on the computed ranges, crop from source and paste into target

            # get the region to copy from the source (bbox_mask)
            src_slice = (slice(y_start_local, y_end_local), slice(x_start_local, x_end_local))
            mask_to_paste = bbox_mask[src_slice]

            # get the region to paste into the target (final_mask)
            dest_slice = (slice(y_start_global, y_end_global), slice(x_start_global, x_end_global))
            paste_region = final_mask[dest_slice]

            # 4. perform paste
            # only paste where mask_to_paste is 1 (foreground)
            valid_paste_mask = (mask_to_paste > 0)
            paste_region[valid_paste_mask] = class_id + 1  # use class_id + 1

        # 6. convert to VTI (using VTK)
        print("Converting final mask to VTI...")

        # 6.1. create vtkImageData
        image_data = vtk.vtkImageData()
        print(f"VTI Image Dimensions: W={W}, H={H}")
        image_data.SetDimensions(W, H, 1)  # VTK order: (X, Y, Z)
        # image_data.SetSpacing(float(pixel_spacing[0]), float(pixel_spacing[1]), slice_thickness)
        image_data.SetSpacing(1, 1, slice_thickness)  # (X, Y, Z) spacing
        image_data.SetOrigin(float(origin[0]), float(origin[1]), float(origin[2]))  # (X, Y, Z) origin

        # 6.2. convert NumPy array to VTK array
        # final_mask (H, W) -> ravel('C') -> (W*H,)

        vtk_data_array = numpy_support.numpy_to_vtk(
            num_array=final_mask.ravel(order='C'),
            deep=True,
            array_type=vtk.VTK_UNSIGNED_CHAR  # corresponds to np.uint8
        )

        # 6.3. set data on vtkImageData
        image_data.GetPointData().SetScalars(vtk_data_array)

        # 6.4. write to memory
        writer = vtk.vtkXMLImageDataWriter()
        writer.SetDataModeToBinary()
        writer.SetInputData(image_data)
        writer.WriteToOutputStringOn()
        writer.Write()

        # get byte content
        vti_content_bytes = writer.GetOutputString()

        # 7. return VTI file
        print("Sending .vti file as response.")
        # ##### TODO: for testing only
        # debug_filename = "debug_vti_response_output.vti"
        # with open(debug_filename, "w", encoding="utf-8") as f:
        #     f.write(vti_content_bytes)
        # print(f"--- debug_vti_response_output saved to {debug_filename} for debugging ---")
        # #####

        return vti_content_bytes

    except Exception as e:
        print(f"Error getting segmentation: {e}")
        import traceback
        traceback.print_exc()  # print detailed error stack trace
        raise HTTPException(status_code=500, detail=str(e))


def rle2Mask(rle: list) -> tuple[np.ndarray, int, int, int, int]:
    """
    Decode RLE (including BBox) into a 2D mask array.
    Returns: (bbox_mask, x1_int, y1_int, x2_int, y2_int)
    """
    if len(rle) < 4:
        # insufficient data
        return np.zeros((0, 0), dtype=np.uint8), 0, 0, 0, 0

    bbox_coords = rle[-4:]
    rle_counts = rle[:-4]

    x1, y1, x2, y2 = map(int, bbox_coords)

    rle_int_list_filter = list(map(int, rle_counts))

    width, height = x2 - x1 + 1, y2 - y1 + 1

    if width <= 0 or height <= 0:
        return np.zeros((0, 0), dtype=np.uint8), x1, y1, x2, y2

    total_pixels = width * height
    decoded = np.zeros(total_pixels, dtype=np.uint8)
    idx = 0
    val = 0

    try:
        for count in rle_int_list_filter:
            end_idx = idx + count
            if end_idx > total_pixels:

                decoded[idx:] = val
                print(f"Warning: RLE data mismatch. Truncating.")
                break

            decoded[idx:end_idx] = val
            idx = end_idx
            val = 1 - val

        decoded_mask = decoded.reshape((width, height), order='F').T
        return decoded_mask, x1, y1, x2, y2

    except Exception as e:
        print(f"Error decoding RLE: {e}")
        return np.zeros((0, 0), dtype=np.uint8), x1, y1, x2, y2

# manifest to dicom sr api for interoperability
@app.post("/manifest_to_dicom_sr")
async def manifest_to_dicom_sr(manifest: Manifest):
    gen = SRGenerator(manifest)
    ds = gen.generate()

    buffer = io.BytesIO()
    ds.save_as(buffer)
    buffer.seek(0)

    filename = f"{manifest.study_instance_uid}_sr.dcm"
    return StreamingResponse(
        buffer,
        media_type="application/dicom",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.post("/dicom_sr_to_manifest")
async def dicom_sr_to_manifest(request: Request):
    dicom_bytes = await request.body()
    ds = pydicom.dcmread(io.BytesIO(dicom_bytes))

    # Extract the compressed manifest
    raw = ds[(0x0043, 0x1010)].value
    # Decompress + decode to text
    manifest_text = gzip.decompress(raw).decode("utf-8")

    # Convert to JSON/dict
    manifest_json = json.loads(manifest_text)

    # Return clean JSON
    return JSONResponse(content=manifest_json)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# DCMQI converter API endpoint (currently disabled) [for future use]
# @app.post("/convert/vti-to-seg")
# async def convert_vti_to_seg(
#     study_uid: str = Form(...),
#     series_uid: str = Form(...),
#     segment_label: str = Form("Segment"),
#     vti_file: UploadFile = Form(...)
# ):
#     temp_dir = Path("temp")
#     temp_dir.mkdir(exist_ok=True)

#     # Save incoming VTI
#     vti_path = temp_dir / f"{series_uid}.vti"
#     with open(vti_path, "wb") as f:
#         f.write(await vti_file.read())

#     # Create descriptor JSON for DCMQI
#     descriptor = {
#         "ContentCreatorName": "VolView",
#         "BodyPartExamined": "UNKNOWN",
#         "SeriesDescription": "Segmentation",
#         "SegmentAlgorithmType": "SEMIAUTOMATIC",
#         "SegmentAlgorithmName": "VolView-Seg",
#         "Segments": [
#             {
#                 "SegmentNumber": 1,
#                 "SegmentLabel": segment_label,
#                 "SegmentAlgorithmType": "SEMIAUTOMATIC",
#                 "SegmentAlgorithmName": "VolView-Seg",
#                 "RecommendedDisplayCIELabValue": [128, 128, 64]
#             }
#         ]
#     }

#     descriptor_path = temp_dir / f"{series_uid}.json"
#     with open(descriptor_path, "w") as f:
#         json.dump(descriptor, f, indent=2)

#     seg_path = temp_dir / f"{series_uid}_seg.dcm"

#     # Run DCMQI converter
#     cmd = [
#         "itkimage2segimage",
#         "--inputImageList", str(vti_path),
#         "--inputDICOMDirectory", ".",  # Only needed if using source images
#         "--outputDICOM", str(seg_path),
#         "--segmentMetadata", str(descriptor_path),
#         "--studyInstanceUID", study_uid,
#         "--seriesInstanceUID", series_uid,
#         "--skipEmptySlices"
#     ]

#     subprocess.run(cmd, check=True)

#     # Return the DICOM-SEG file
#     return FileResponse(
#         seg_path,
#         media_type="application/dicom",
#         filename=f"{series_uid}_seg.dcm"
#     )
