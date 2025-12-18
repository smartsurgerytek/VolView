import gzip
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
from PIL import Image
import base64
import vtk  # VTK
from vtk.util import numpy_support

from .models import Manifest
import settings
from sr_generator import SRGenerator

from .utils1 import (
    DotDict,
    get_filepath_for_subject,
    read_file_from_zip,
    create_empty_sr,
    update_general_module,
    update_patient_module,
    update_sr_content_module,
    update_private_tags
)

from .utils2 import (
    Rulers,
    Tools,
    Layout,
    ViewerSession,
    generate_data_structure,
    create_volview_zip_from_memory
)

from dicomweb_client.api import DICOMwebClient

# Configs
dicomweb_url = settings.DICOMWEB_URL  # "http://localhost:8080/dicom-web"
client = DICOMwebClient(url=dicomweb_url)

app = FastAPI()

# ------------------- FastAPI events -------------------
@app.on_event("startup")
async def startup_event():
    app.state.http_client = httpx.AsyncClient(verify=False)

@app.on_event("shutdown")
async def shutdown_event():
    await app.state.http_client.aclose()

# ------------------- /api/save -------------------
@app.post("/api/save")
async def save_session_to_sr_and_seg(request: Request):
    try:
        print("Received /api/save request")
        zip_data = await request.body()
        print(f"Zip data size: {len(zip_data)} bytes")

        if not zip_data:
            raise ValueError("No zip data received in the request body")
        
        zip_file_in_memory = io.BytesIO(zip_data)
        manifest_string = read_file_from_zip(zip_file_in_memory, "manifest.json")
        manifest = DotDict.from_dict(json.loads(manifest_string))
        print("Successfully read manifest.json from zip")

        # Get any subject dicom file to get study_instance_uid
        path_value = list(manifest['datasetFilePath'].values())[0]
        subject = read_file_from_zip(zip_file_in_memory, path_value)
        ds = pydicom.dcmread(io.BytesIO(subject))
        study_instance_uid = ds.get('StudyInstanceUID')
        patient_id = ds.get('PatientID')

        subjects = [dataset for dataset in manifest['datasets']]
        measurements = [ruler for ruler in manifest['tools']['rulers']['tools']]
        sr_index = 1

        # Check existing series
        series_instance_UID = await get_series_uid()

        # Delete series before creating new
        delete_response = await delete_orthanc_series(patient_id, study_instance_uid, series_instance_UID)
        print("delete_response:", delete_response)

        for subject in subjects:
            filepath = get_filepath_for_subject(subject, manifest)
            print('filepath:', filepath)
            subject_ds = pydicom.dcmread(io.BytesIO(read_file_from_zip(zip_file_in_memory, filepath)))
        
            for measurement in measurements:
                if subject['id'] != measurement['imageID']:
                    continue

                print('start process measurement id:', measurement['id'])
                print(measurement)

                sr_ds = create_empty_sr()
                sr_ds = update_general_module(sr_ds, subject_ds)
                sr_ds = update_patient_module(sr_ds, subject_ds)
                sr_ds = update_private_tags(sr_ds, measurement)
                sr_ds.SeriesInstanceUID = series_instance_UID

                response = client.store_instances(datasets=[sr_ds])
                sr_index += 1

            print('--------------------------')

        return JSONResponse(content={'success': True}, status_code=200)

    except Exception as e:
        print(f"Error saving session: {e}")
        return JSONResponse(content={'success': False, 'error': str(e)}, status_code=500)

# ------------------- /api/load -------------------
@app.post("/api/load")
async def load_session(request: Request):
    try:
        print("Received /api/load request")
        study_instance_uid = (await request.json()).get('StudyInstanceUID')
        if not study_instance_uid:
            raise ValueError("StudyInstanceUID is required in the request body")
        print(f"StudyInstanceUID: {study_instance_uid}")

        instances = client.search_for_instances(study_instance_uid=study_instance_uid)
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

            datasetId = f"{ds.get('SeriesInstanceUID')}.1{ds.get('Rows')}{ds.get('Columns')}{ds.get('SeriesDate')}.1D000000S0D000000S0D000000S0D000000S1D000000S0D000000"
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
            ),
            layout=Layout(name="Axial Only", direction="H", items=["Axial"]),
            views=[],
            parentToLayers=[],
            primarySelection=dataset_uids[-1]
        )

        session_zip_bytes = create_volview_zip_from_memory(
            viewer_session=viewer_session,
            generated_paths=generated_paths,
            subject_files=subject_files,
            client=client
        )

        print(f"Session ZIP size: {len(session_zip_bytes)} bytes")
        return Response(content=session_zip_bytes, media_type="application/zip")

    except Exception as e:
        print(f"Error loading session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ------------------- /api/load_with_anno -------------------
@app.post("/api/load_with_anno")
async def load_session_with_anno(request: Request):
    try:
        print("Received /api/load_with_anno request")
        apiClient: httpx.AsyncClient = app.state.http_client
        study_instance_uid = (await request.json()).get('StudyInstanceUID')
        if not study_instance_uid:
            raise ValueError("StudyInstanceUID is required in the request body")
        print(f"StudyInstanceUID: {study_instance_uid}")

        instances = client.search_for_instances(study_instance_uid=study_instance_uid)
        if len(instances) == 0:
            raise ValueError(f"No instances found for StudyInstanceUID: {study_instance_uid}")
        print(f"Found {len(instances)} instances in the study.")

        dataset_uids = []
        subject_files = {}
        measurement_data = []
        viewer_session = None
        is_manifest_from_sr = False

        for instance in instances:
            ds = client.retrieve_instance(
                study_instance_uid=instance.get('0020000D')['Value'][0],
                series_instance_uid=instance.get('0020000E')['Value'][0],
                sop_instance_uid=instance.get('00080018')['Value'][0],
            )

            if ds.get('Modality') not in ['SR', 'SEG']:
                print('Found subject instance:', ds.get('SOPInstanceUID'))
                datasetId = f"{ds.get('SeriesInstanceUID')}.1{ds.get('Rows')}{ds.get('Columns')}{ds.get('SeriesDate')}.1D000000S0D000000S0D000000S0D000000S1D000000S0D000000"
                dataset_uids.append(datasetId)
                subject_filename = f"{ds.get('PatientID')}-{ds.get('StudyDate')}-{ds.get('InstanceNumber')}.dcm"
                subject_files[subject_filename] = [ds.get('SOPInstanceUID'), ds.get('SeriesInstanceUID'), ds.get('StudyInstanceUID')]

            elif ds.get('Modality') == 'SR':
                print('Found SR instance:', ds.get('SOPInstanceUID'))
                abpapi_url = settings.ABPAPI_URL + "/manifest"
                print(str(abpapi_url))
                response = await apiClient.get(str(abpapi_url), params={"studyInstanceUID": study_instance_uid})
                response.raise_for_status()
                viewer_session = ViewerSession(**response.json())
                is_manifest_from_sr = True

        generated_datasets, generated_sources, generated_paths = generate_data_structure(dataset_uids, subject_files)

        if not viewer_session:
            print("No SR found in the study. Creating empty viewer session.")
            fake_layout = Layout(name="Axial Only", direction="H", items=["Axial"])
            fake_tools = Tools(
                crosshairs={"position": (0, 0, 0)},
                paint={"activeSegmentGroupID": None, "activeSegment": 1, "brushSize": 4},
                crop={},
                current="Ruler",
                polygons={"tools": [], "labels": {}},
                rectangles={"tools": [], "labels": {}},
                rulers=Rulers(tools=measurement_data, labels={}),
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

        session_zip_bytes = create_volview_zip_from_memory(
            viewer_session=viewer_session,
            generated_paths=generated_paths,
            subject_files=subject_files,
            client=client,
            is_manifest_from_sr=is_manifest_from_sr
        )

        print(f"Session ZIP size: {len(session_zip_bytes)} bytes")
        return Response(content=session_zip_bytes, media_type="application/zip")

    except Exception as e:
        print(f"Error loading session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ------------------- Series helpers -------------------
async def get_series_uid():
    series = client.search_for_series(search_filters={'SeriesDescription': 'Measurement Report'})
    if series:
        print("Existing Measurement Report series found in the study.")
        return series[0].get('0020000E')['Value'][0]
    else:
        print("No existing Measurement Report series found. A new series will be created.")
        return generate_uid()

ORTHANC_BASE_URL = "http://localhost:8080"

async def delete_orthanc_series(patient_id: str, study_instance_uid: str, series_instance_uid: str) -> dict:
    orthanc_id = None
    try:
        concatenated_string = f"{patient_id}|{study_instance_uid}|{series_instance_uid}"
        concatenated_bytes = concatenated_string.encode('utf-8')
        sha1_hash_obj = hashlib.sha1(concatenated_bytes)
        raw_hash = sha1_hash_obj.hexdigest()
        parts = [raw_hash[i:i+8] for i in range(0, len(raw_hash), 8)]
        orthanc_id = "-".join(parts)

        url = f"{ORTHANC_BASE_URL}/series/{orthanc_id}"
        async with httpx.AsyncClient() as client:
            print(f"--- Deleting Series --- {url}")
            response = await client.delete(url)
            response.raise_for_status()
            try:
                response_data = response.json()
            except json.JSONDecodeError:
                response_data = response.text
            print(f"Successfully deleted Series (status: {response.status_code})")
            return {"success": True, "status_code": response.status_code, "orthanc_id": orthanc_id, "data": response_data}

    except httpx.HTTPStatusError as e:
        print(f"HTTP Error: {e.response.status_code} - {e.response.text}")
        return {"success": False, "status_code": e.response.status_code, "orthanc_id": orthanc_id, "error": "HTTP Error", "details": e.response.text}
    except httpx.RequestError as e:
        print(f"Connection Error: {e}")
        return {"success": False, "status_code": None, "orthanc_id": orthanc_id, "error": "Connection Error", "details": str(e)}
    except Exception as e:
        print(f"Unexpected Error: {e}")
        return {"success": False, "status_code": None, "orthanc_id": orthanc_id, "error": "Unexpected Error", "details": str(e)}

# ------------------- Segmentation -------------------
@app.post("/api/get_segmentation")
async def get_segmentation(request: Request):
    try:
        print("Received /api/get_segmentation request")
        study_instance_uid = (await request.json()).get('StudyInstanceUID')
        series_instance_uid = (await request.json()).get('SeriesInstanceUID')
        sop_instance_uid = (await request.json()).get('SopInstanceUID')

        if not study_instance_uid or not series_instance_uid or not sop_instance_uid:
            raise ValueError("StudyInstanceUID, SeriesInstanceUID and SopInstanceUID are required")

        instance = client.retrieve_instance(
            study_instance_uid=study_instance_uid,
            series_instance_uid=series_instance_uid,
            sop_instance_uid=sop_instance_uid,
        )

        instance_base64 = get_base64_string(instance)
        segmentation_response = await get_dentistry_segmentation(instance_base64)

        if 'yolo_results' not in segmentation_response or 'yolov8_contents' not in segmentation_response['yolo_results']:
            raise ValueError("API response does not contain 'yolo_results.yolov8_contents'")

        vti_content_bytes = get_vti_file(instance, segmentation_response)

        return Response(
            content=vti_content_bytes,
            media_type="application/xml",
            headers={"Content-Disposition": f"attachment; filename=segmentation_{sop_instance_uid}.vti"}
        )

    except Exception as e:
        print(f"Error getting segmentation: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ------------------- Helpers -------------------
def get_base64_string(ds):
    new_image = ds.pixel_array.astype(float)
    scaled_image = (np.maximum(new_image, 0) / new_image.max()) * 255.0
    scaled_image = np.uint8(scaled_image)
    final_image = Image.fromarray(scaled_image)

    buffered = io.BytesIO()
    final_image.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

async def get_dentistry_segmentation(base64_string: str):
    url = "https://api-int.smartsurgerytek.net/v1/pa_segmentation_cvat"
    payload = {"image": base64_string}
    query_params = {"key": "apikey"}
    timeout_config = httpx.Timeout(30.0, connect=5.0)

    async with httpx.AsyncClient(timeout=timeout_config) as client:
        try:
            response = await client.post(url, json=payload, params=query_params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error calling segmentation API: {e}")
            raise

def get_vti_file(instance, segmentation_response):
    try:
        H, W = instance.Rows, instance.Columns
        pixel_spacing = [1.0, 1.0]
        slice_thickness = float(instance.SliceThickness if "SliceThickness" in instance else 1.0)
        origin = instance.ImagePositionPatient if "ImagePositionPatient" in instance else [0.0, 0.0, 0.0]

        final_mask = np.zeros((H, W), dtype=np.uint8)

        yolov8_contents = segmentation_response['yolo_results']['yolov8_contents']
        for obj in yolov8_contents:
            points = obj.get('points')
            class_id = obj.get('class_id')
            if not points or class_id is None:
                continue
            bbox_mask, x1, y1, x2, y2 = rle2Mask(points)
            if bbox_mask.size == 0:
                continue
            x_start_global = max(x1, 0)
            y_start_global = max(y1, 0)
            x_end_global = min(x2 + 1, W)
            y_end_global = min(y2 + 1, H)
            if x_start_global >= x_end_global or y_start_global >= y_end_global:
                continue
            x_start_local = x_start_global - x1
            y_start_local = y_start_global - y1
            x_end_local = x_end_global - x1
            y_end_local = y_end_global - y1
            src_slice = (slice(y_start_local, y_end_local), slice(x_start_local, x_end_local))
            mask_to_paste = bbox_mask[src_slice]
            dest_slice = (slice(y_start_global, y_end_global), slice(x_start_global, x_end_global))
            paste_region = final_mask[dest_slice]
            valid_paste_mask = (mask_to_paste == 1)
            paste_region[valid_paste_mask] = class_id + 1

        image_data = vtk.vtkImageData()
        image_data.SetDimensions(W, H, 1)
        image_data.SetSpacing(float(pixel_spacing[1]), float(pixel_spacing[0]), slice_thickness)
        image_data.SetOrigin(float(origin[0]), float(origin[1]), float(origin[2]))

        vtk_data_array = numpy_support.numpy_to_vtk(num_array=final_mask.ravel(order='C'), deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
        image_data.GetPointData().SetScalars(vtk_data_array)

        writer = vtk.vtkXMLImageDataWriter()
        writer.SetDataModeToBinary()
        writer.SetInputData(image_data)
        writer.WriteToOutputStringOn()
        writer.Write()
        return writer.GetOutputString()

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

def rle2Mask(rle: list) -> tuple[np.ndarray, int, int, int, int]:
    if len(rle) < 4:
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
                break
            decoded[idx:end_idx] = val
            idx = end_idx
            val = 1 - val
        decoded_mask = decoded.reshape((width, height), order='F').T
        return decoded_mask, x1, y1, x2, y2
    except Exception as e:
        return np.zeros((0, 0), dtype=np.uint8), x1, y1, x2, y2

# ------------------- Manifest <-> DICOM SR -------------------
@app.post("/manifest_to_dicom_sr")
async def manifest_to_dicom_sr(manifest: Manifest):
    gen = SRGenerator(manifest)
    ds = gen.generate()
    buffer = io.BytesIO()
    ds.save_as(buffer)
    buffer.seek(0)
    filename = f"{manifest.study_instance_uid}_sr.dcm"
    return StreamingResponse(buffer, media_type="application/dicom", headers={"Content-Disposition": f"attachment; filename={filename}"})

@app.post("/dicom_sr_to_manifest")
async def dicom_sr_to_manifest(request: Request):
    dicom_bytes = await request.body()
    ds = pydicom.dcmread(io.BytesIO(dicom_bytes))
    raw = ds[(0x0043, 0x1010)].value
    manifest_text = gzip.decompress(raw).decode("utf-8")
    manifest_json = json.loads(manifest_text)
    return JSONResponse(content=manifest_json)

# ------------------- Middleware -------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
