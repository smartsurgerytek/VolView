from typing import Dict
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Request, HTTPException  
from fastapi.responses import JSONResponse

import zipfile
import json
import io
import pydicom
from pydicom.uid import generate_uid

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

import httpx
import hashlib

# 將 Orthanc 的基礎 URL 設為一個常數，方便未來修改
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
    
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)