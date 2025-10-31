from typing import Dict
from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
    Tools,
    Layout,
    ViewerSession,
    generate_data_structure,
    create_volview_zip_from_memory
)

from volview_server import VolViewApi

from dicomweb_client.api import DICOMwebClient

# TODO: url should be configured
client = DICOMwebClient(url="http://localhost:8080/dicom-web")

volview = VolViewApi()

app = FastAPI()

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
                # Todo: Handle response
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
                
            # simulate datasetid
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
                    rulers= Rulers(tools=[], labels={}),
                    ),
                layout=Layout(name="Axial Only", direction="H", items=["Axial"]),
                views=[],
                parentToLayers=[],
                primarySelection=dataset_uids[-1]
            )
        
        # Save
        session_zip_bytes = create_volview_zip_from_memory(
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

        for instance in instances:
            ds = client.retrieve_instance(
                study_instance_uid=instance.get('0020000D')['Value'][0],
                series_instance_uid=instance.get('0020000E')['Value'][0],
                sop_instance_uid=instance.get('00080018')['Value'][0],
            )
                
            # print('======================')
            # print(ds.get('SOPInstanceUID'))
            # print(ds.get('Modality'))
            # print(ds.get('ReferencedSOPInstanceUID'))

            # simulate datasetid
            if((ds.get('Modality') != 'SR') and (ds.get('Modality') != 'SEG')):
                # try to caculate datasetId
                datasetId = f"{ds.get('SeriesInstanceUID')}.1{ds.get('Rows')}{ds.get('Columns')}{ds.get('SeriesDate')}.1D000000S0D000000S0D000000S0D000000S1D000000S0D000000"
                dataset_uids.append(datasetId)
                # print('datasetId:', datasetId)
                
                subject_filename = f"{ds.get('PatientID')}-{ds.get('StudyDate')}-{ds.get('InstanceNumber')}.dcm"
                subject_files[subject_filename] = [ds.get('SOPInstanceUID'), ds.get('SeriesInstanceUID'), ds.get('StudyInstanceUID')]
                print('subject_files:', subject_files)

            # subject dicom don't have this tag
            measurement = ds.get((0x7777,0x12))

            if(measurement):
                measurement_dict = DotDict.from_dict(json.loads(measurement.value)) 
                measurement_data.append(measurement_dict)
                # print('measurement data:', measurement_dict)     
                # print('measurement id:', measurement_dict['id'])

            # print('======================')

        generated_datasets, generated_sources, generated_paths = generate_data_structure(dataset_uids, subject_files)

        fake_tools = Tools(
            crosshairs={"position": (0, 0, 0)},
            paint={"activeSegmentGroupID": None, "activeSegment": 1, "brushSize": 4},
            crop={},
            current="Ruler",
            polygons={"tools": [], "labels": {}},
            rectangles={"tools": [], "labels": {}},
            rulers= Rulers(tools=measurement_data, labels={}),
            )
        
        fake_layout = Layout(name="Axial Only", direction="H", items=["Axial"])

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

        # Save
        session_zip_bytes = create_volview_zip_from_memory(
            viewer_session=viewer_session,
            generated_paths=generated_paths,
            subject_files=subject_files,
            client=client)
        
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


# TODO:read ORTHANC_BASE_URL from .env
ORTHANC_BASE_URL = "http://localhost:8080"

async def delete_orthanc_series(
    patient_id: str, 
    study_instance_uid: str, 
    series_instance_uid: str
) -> dict:
    """
    發送一個非同步的 DELETE 請求到 Orthanc 伺服器以刪除指定的 Series。
    
    此函式會根據 PatientID, StudyInstanceUID, 和 SeriesInstanceUID
    計算出 Orthanc 的 SHA-1 ID (Stable Identifier)，然後才發送請求。

    Args:
        patient_id (str): DICOM Tag (0010,0020) 的值
        study_instance_uid (str): DICOM Tag (0020,000D) 的值
        series_instance_uid (str): DICOM Tag (0020,000E) 的值

    Returns:
        一個包含請求結果的字典。
    """
    
    orthanc_id = None # 先初始化
    
    try:
        # --- 1. 計算 Orthanc SHA-1 ID ---
        # 根據規則：SHA-1(PatientID + StudyInstanceUID + SeriesInstanceUID)
        # 確保字串串接順序和內容完全正確
        concatenated_string = f"{patient_id}|{study_instance_uid}|{series_instance_uid}"
        
        # 將字串編碼為 bytes (SHA-1 必須作用在 bytes 上)
        concatenated_bytes = concatenated_string.encode('utf-8')
        sha1_hash_obj = hashlib.sha1(concatenated_bytes)
        raw_hash = sha1_hash_obj.hexdigest()
        parts = []
        for i in range(0, len(raw_hash), 8):
            parts.append(raw_hash[i:i+8])
        orthanc_id = "-".join(parts)
        # 建立 SHA-1 hash 物件
        #sha1_hash_obj = hashlib.sha1(concatenated_bytes)
        
        # 取得 16 進位字串 (這就是 Orthanc ID)
        #orthanc_id = sha1_hash_obj.hexdigest()
        # --- ------------------------ ---

        # 2. 組合完整的 API 網址 (使用計算出來的 hash ID)
        url = f"{ORTHANC_BASE_URL}/series/{orthanc_id}"
        
        # 3. 發送請求
        async with httpx.AsyncClient() as client:
            print(f"--- 準備刪除 Series ---")
            print(f"PatientID: {patient_id}")
            print(f"StudyInstanceUID: {study_instance_uid}")
            print(f"SeriesInstanceUID: {series_instance_uid}")
            print(f"Calculated Orthanc ID (SHA-1): {orthanc_id}")
            print(f"正在發送 DELETE 請求至: {url}")
            
            response = await client.delete(url)
            
            # 檢查 HTTP 狀態碼
            response.raise_for_status()

            # --- 請求成功 (2xx 狀態碼) ---
            try:
                # 嘗試解析 Orthanc 回傳的 JSON 
                response_data = response.json()
            except json.JSONDecodeError:
                # 如果 Orthanc 回傳的是空內容或純文字
                response_data = response.text
                
            print(f"成功刪除 Series (狀態碼: {response.status_code})")
            return {
                "success": True,
                "status_code": response.status_code,
                "orthanc_id": orthanc_id,
                "data": response_data
            }

    except httpx.HTTPStatusError as e:
        # 處理 HTTP 錯誤 (例如 404, 405, 500)
        print(f"HTTP 錯誤: {e.response.status_code} - {e.response.text}")
        return {
            "success": False,
            "status_code": e.response.status_code,
            "orthanc_id": orthanc_id, # 仍然回傳 ID 方便除錯
            "error": "HTTP Error",
            "details": e.response.text
        }
    except httpx.RequestError as e:
        # 處理連線錯誤 (例如連線被拒絕)
        print(f"連線錯誤: {e}")
        return {
            "success": False,
            "status_code": None,
            "orthanc_id": orthanc_id,
            "error": "Connection Error",
            "details": str(e)
        }
    except Exception as e:
        # 捕捉其他未預期的錯誤
        print(f"發生未預期錯誤: {e}")
        return {
            "success": False,
            "status_code": None,
            "orthanc_id": orthanc_id,
            "error": "Unexpected Error",
            "details": str(e)
        }

@app.post("/api/get_measurement")
async def get_measurement(request: Request):
    try:
        print("Received /api/get_measurement request")

        study_instance_uid = (await request.json()).get('StudyInstanceUID')
        series_instance_uid = (await request.json()).get('SeriesInstanceUID')
        sop_instance_uid = (await request.json()).get('SopInstanceUID')
        current_image_id = (await request.json()).get('ImageID')
        scale_x = (await request.json()).get('ScaleX')
        scale_y = (await request.json()).get('ScaleY')

        if not study_instance_uid :
            raise ValueError("StudyInstanceUID is required in the request body")
        
        if not series_instance_uid :
            raise ValueError("SeriesInstanceUID is required in the request body")
        
        if not sop_instance_uid:
            raise ValueError("SopInstanceUID is required in the request body")
        
        if not scale_x:
            raise ValueError("ScaleX is required in the request body")
           
        if not scale_y:
            raise ValueError("ScaleY is required in the request body")
     
        if scale_x == 1:
            scale_x = 0.03125

        if scale_y == 1:
            scale_x = 0.03125

        # Get Dicom Instance
        instance = client.retrieve_instance(
                study_instance_uid=study_instance_uid,
                series_instance_uid=series_instance_uid,
                sop_instance_uid=sop_instance_uid,
            )
       
        # Get Image base64 String 
        instance_base64 = get_base64_string(instance)

        # invoke dentistry api
        measurement_response = await get_dentistry_measurement(instance_base64,scale_x, scale_y)

        ruler_list = get_rulers(measurement_response, current_image_id)

        return JSONResponse(
                content={
                    'success': True,
                    'data': ruler_list},  
                status_code=200
            )

    except Exception as e:
        print(f"Error getting measurement: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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

        # Get Dicom Instance
        instance = client.retrieve_instance(
                study_instance_uid=study_instance_uid,
                series_instance_uid=series_instance_uid,
                sop_instance_uid=sop_instance_uid,
            )

        # Get Image base64 String
        instance_base64 = get_base64_string(instance)

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

def get_base64_string(ds):
    new_image = ds.pixel_array.astype(float)

    # Rescaling the image
    scaled_image = (np.maximum(new_image, 0) / new_image.max()) * 255.0

    scaled_image = np.uint8(scaled_image)
    final_image = Image.fromarray(scaled_image)

    # save
    buffered = io.BytesIO()
    final_image.save(buffered, format="PNG")

    base64_string = base64.b64encode(buffered.getvalue()).decode('utf-8')
    
    return base64_string

async def get_dentistry_measurement(base64_string: str, scale_x: float, scale_y: float):

    url = "https://api-int.smartsurgerytek.net/v1/pa_measure_dict"
    payload = {
            "image": base64_string,
            "scale_x": scale_x,
            "scale_y": scale_y
        }

    # TODO: read the api key in .env
    query_params = {
        "key": "apikey"
        }

    timeout_config = httpx.Timeout(30.0, connect=5.0)

    async with httpx.AsyncClient(timeout=timeout_config) as client:
        try:
            print(f"--- ready to invoke Inference API: {url} ---")
            
            response = await client.post(
                url,
                json=payload,
                params=query_params
            )
            
            response.raise_for_status()

            response_data = response.json()
            print(f"成功取得 API 回應 (狀態碼: {response.status_code})")
            #print(response_data) # 印出 API 回傳的資料
            return response_data

        except httpx.HTTPStatusError as e:
            print(f"API 請求錯誤: {e.response.status_code} - {e.response.text}")
        except httpx.RequestError as e:
            print(f"網路連線錯誤: {e}")
            raise
        except json.JSONDecodeError:
            print(f"無法解析 API 回應 (非 JSON): {response.text}")
            raise

async def get_dentistry_segmentation(base64_string: str):

    url = "https://api-int.smartsurgerytek.net/v1/pa_segmentation_cvat"
    payload = {
            "image": base64_string
        }

    query_params = {
        "key": "apikey"
        }
    
    timeout_config = httpx.Timeout(30.0, connect=5.0)

    async with httpx.AsyncClient(timeout=timeout_config) as client:
        try:
            print(f"--- ready to invoke Inference API: {url} ---")
            
            response = await client.post(
                url,
                json=payload,
                params=query_params
            )
            
            response.raise_for_status()

            response_data = response.json()
            print(f"成功取得 API 回應 (狀態碼: {response.status_code})")
            #print(response_data) # 印出 API 回傳的資料
            return response_data

        except httpx.HTTPStatusError as e:
            print(f"API 請求錯誤: {e.response.status_code} - {e.response.text}")
        except httpx.RequestError as e:
            print(f"網路連線錯誤: {e}")
            raise
        except json.JSONDecodeError:
            print(f"無法解析 API 回應 (非 JSON): {response.text}")
            raise

def get_rulers(api_response, image_id):

    measurements = api_response.get('measurements')

    rulers_list = []

    for measurement in measurements:
        pair_measurements = measurement.get('pair_measurements')
        for pair_measurement in pair_measurements:

            # point
            cej = pair_measurement.get('CEJ')
            alc = pair_measurement.get('ALC')
            apex = pair_measurement.get('APEX')

            ruler_cal = {
                'stage': pair_measurement.get('stage'),
                'firstPoint': [cej[0], cej[1], 0],
                'secondPoint': [alc[0], alc[1], 0],
                'imageID': image_id,
                'slice': 0,
                'placing': False,
                'frameOfReference': {
                    'planeNormal': [0, 0, 1],
                    'planeOrigin': [0, 0, 0]
                }
            }

            ruler_trl = {
                'stage': 'trl',
                'firstPoint': [cej[0], cej[1], 0],
                'secondPoint': [apex[0], apex[1], 0],
                'imageID': image_id,
                'slice': 0,
                'placing': False,
                'frameOfReference': {
                    'planeNormal': [0, 0, 1],
                    'planeOrigin': [0, 0, 0]
                }
            }

            rulers_list.append(ruler_cal)
            rulers_list.append(ruler_trl)

    return rulers_list

def get_vti_file(instance, segmentation_response):
    try:
        # 3. get metadata
        H, W = instance.Rows, instance.Columns

        ## afeter set PixelSpacing=[1.0, 1.0] brush works!
        pixel_spacing = [1.0, 1.0] ## instance.PixelSpacing if "PixelSpacing" in instance else [1.0, 1.0]
        slice_thickness = float(instance.SliceThickness if "SliceThickness" in instance else 1.0)
        origin = instance.ImagePositionPatient if "ImagePositionPatient" in instance else [0.0, 0.0, 0.0]
        
        # 4. 建立畫布
        # *** 假設: class ID 範圍為 0-255 (uint8) ***
        final_mask = np.zeros((H, W), dtype=np.uint8)
        
        # 5. 解碼 RLE 並合成 Mask
        # *** 假設: API 回應的結構如同您的範例 ***
        # (您可能需要根據您的 API 回應調整 'yolo_results' 和 'yolov8_contents')
        if 'yolo_results' not in segmentation_response or 'yolov8_contents' not in segmentation_response['yolo_results']:
            raise ValueError("API response does not contain 'yolo_results.yolov8_contents'")
                    
        yolov8_contents = segmentation_response['yolo_results']['yolov8_contents']
            
        print(f"Processing {len(yolov8_contents)} segmented objects...")

        for obj in yolov8_contents:
            points = obj.get('points')
            class_id = obj.get('class_id') 

            if not points or class_id is None:
                continue

            # 1. 解碼 RLE
            bbox_mask, x1, y1, x2, y2 = rle2Mask(points)
                
            if bbox_mask.size == 0:
                print(f"Skipping empty mask for class {class_id}")
                continue

            # 2. 尋找 來源 (bbox_mask) 和 目標 (final_mask) 之間的重疊區域
            
            # --- 2a. 計算重疊區域的「全域座標」(相對於 final_mask) ---
            # BBox 的 x2, y2 是包含在內的，所以結束點要 +1
            x_start_global = max(x1, 0)
            y_start_global = max(y1, 0)
            x_end_global = min(x2 + 1, W) # W 是 final_mask 的寬度
            y_end_global = min(y2 + 1, H) # H 是 final_mask 的高度

            # --- 2b. 如果根本沒有重疊，就跳過 ---
            if x_start_global >= x_end_global or y_start_global >= y_end_global:
                print(f"Skipping mask for class {class_id} (BBox completely out of bounds)")
                continue

            # --- 2c. 計算重疊區域的「區域座標」(相對於 bbox_mask) ---
            x_start_local = x_start_global - x1
            y_start_local = y_start_global - y1
            x_end_local = x_end_global - x1
            y_end_local = y_end_global - y1

            # 3. 根據計算好的範圍，從 來源(src) 裁切並貼到 目標(dest)
            
            # 取得 來源(bbox_mask) 中要被複製的區域
            src_slice = (slice(y_start_local, y_end_local), slice(x_start_local, x_end_local))
            mask_to_paste = bbox_mask[src_slice]
            
            # 取得 目標(final_mask) 中要被貼上的區域
            dest_slice = (slice(y_start_global, y_end_global), slice(x_start_global, x_end_global))
            paste_region = final_mask[dest_slice]

            # 4. 執行貼上
            # 只在 mask_to_paste 為 1 (前景) 的地方貼上
            valid_paste_mask = (mask_to_paste == 1)
            paste_region[valid_paste_mask] = class_id + 1 # 使用 class_id + 1
            
        # 6. 轉換為 VTI (使用 VTK)
        print("Converting final mask to VTI...")

        # 6.1. 建立 vtkImageData
        image_data = vtk.vtkImageData()
        image_data.SetDimensions(W, H, 1) # VTK 順序: (X, Y, Z)
        image_data.SetSpacing(float(pixel_spacing[1]), float(pixel_spacing[0]), slice_thickness) # (X, Y, Z) Spacing
        image_data.SetOrigin(float(origin[0]), float(origin[1]), float(origin[2])) # (X, Y, Z) Origin

        # 6.2. 轉換 NumPy 陣列為 VTK 陣列
        # final_mask (H, W) -> ravel('C') -> (W*H,)
        vtk_data_array = numpy_support.numpy_to_vtk(
            num_array=final_mask.ravel(order='C'),
            deep=True,
            array_type=vtk.VTK_UNSIGNED_CHAR # 對應 np.uint8
        )
            
        # 6.3. 將資料設定到 vtkImageData
        image_data.GetPointData().SetScalars(vtk_data_array)

        # 6.4. 寫入記憶體
        writer = vtk.vtkXMLImageDataWriter()
        writer.SetDataModeToBinary()
        writer.SetInputData(image_data)
        writer.WriteToOutputStringOn()
        writer.Write()
        
        # 取得位元組資料
        vti_content_bytes = writer.GetOutputString()

        # 7. 回傳 VTI 檔案
        print("Sending .vti file as response.")
        
        # ##### TODO: only for testing
        # debug_filename = "debug_vti_response_output.vti"
        # with open(debug_filename, "w", encoding="utf-8") as f:
        #     f.write(vti_content_bytes)
        # print(f"--- debug_vti_response_output 已儲存到 {debug_filename} 供除錯 ---")
        # #####
        
        return vti_content_bytes
        
    except Exception as e:
        print(f"Error getting segmentation: {e}")
        import traceback
        traceback.print_exc() # 印出詳細的錯誤堆疊
        raise HTTPException(status_code=500, detail=str(e))

def rle2Mask(rle: list) -> tuple[np.ndarray, int, int, int, int]:
    """
    將 RLE (包含 BBox) 解碼為 2D 遮罩陣列
    返回: (bbox_mask, x1_int, y1_int, x2_int, y2_int)
    """
    if len(rle) < 4:
        # 資料不足
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
    
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)