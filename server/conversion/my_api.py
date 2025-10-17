from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Request, HTTPException  
from fastapi.responses import JSONResponse

import zipfile
import json
import io
import pydicom
import httpx
import uuid
import os

from datetime import datetime
from utils1 import (
    DotDict,
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

client = DICOMwebClient(url="http://localhost:8080/dicom-web")

volview = VolViewApi()

app = FastAPI()

ORTHANC_DICOMWEB_URL = "http://localhost:8080/dicom-web"

# TODO: Need to think about that we need to restrict the scope of a sesssion.zip

@app.post("/api/save")  
async def save_session_to_sr_and_seg(request: Request):  
    try: 
        print("Received /api/save request")
        zip_data = await request.body()

        print(f"Zip data size: {len(zip_data)} bytes")

        if not zip_data:
            raise ValueError("No zip data received in the request body")

        ## subject file : the file we made annotaion on
        subject_ds = None
        subject_ds_array = [] # TODO: subject would be multiple

        ## manifest Dictionary
        manifest = None

        ## vti file content in bytes
        ## TODO: will process segmentation later
        vti_data = []

        ## private tag group_number
        group_number = 0x7777
        creator_id = "SST_VOLVIEW_METADATA"

        dataset_ids_element = 0x11
        measurement_rulers = 0x12

        zip_file_in_memory = io.BytesIO(zip_data)

        with zipfile.ZipFile(zip_file_in_memory, 'r') as zf:
            # Find manifest.json and vti file (only one)
            for filename in zf.namelist():
                if filename.endswith('manifest.json'):
                    # Read and decode directly
                    manifest_string = zf.read(filename).decode('utf-8')
                    # Parse JSON using DotDict
                    manifest = DotDict.from_dict(json.loads(manifest_string))
                    print("Successfully parsed manifest.json")

                # Find the vti file under the labels folder (assumed only one)
                if 'labels/' in filename and filename.endswith('.vti'):
                    # Read the binary content of the vti file
                    vti = zf.read(filename)
                    vti_data.append(vti)
                    print(f"Successfully read VTI file: {filename}")

                # Find the dcm file under the data folder
                # TODO: assumed only one, if multiple, the cide right now will take the last one
                if 'data/' in filename and filename.endswith('.dcm'):
                    # Read the dicom file
                    subject_ds = pydicom.dcmread(io.BytesIO(zf.read(filename)))
                    subject_ds_array.append(subject_ds)
                    print(f"Successfully read dicom file: {filename}")

        if(manifest is None):
            raise ValueError("manifest is None")

        if(subject_ds is None):
            raise ValueError("original_ds is None")

        ## process manifest.json
        print("dataset count:",len(manifest.get('datasets')))

        dataset_ids = []

        for dataset in manifest.get('datasets'):
            dataset_ids.append(dataset.get('id'))

        measurement_data = manifest.get('tools').get('rulers')
        print("measurement_data:", measurement_data)

        ## Create SR file
        sr_ds = create_empty_sr()
        sr_ds = update_general_module(sr_ds, subject_ds)
        sr_ds = update_patient_module(sr_ds, subject_ds)
        # sr_ds = update_sr_content_module(sr_ds)

        ## Write Private Tag

        ### Creator Id : To Recognize our private tag
        sr_ds.add_new((group_number, 0x0010), 'LO', creator_id)

        ### Dataset ID : To store VolView Dataset IDs
        sr_ds.add_new((group_number, dataset_ids_element), 'UT', dataset_ids)

        ### Measurement : To store Ruler Measurement Data
        sr_ds.add_new((group_number, measurement_rulers), 'UT', json.dumps(measurement_data))

        # --- DICOMweb STOW-RS Uplaod---
        print("Preparing to send SR file to PACS via DICOMweb STOW-RS...")

        response_dataset = client.store_instances(datasets=[sr_ds])

        print("Successfully stored SR file in PACS via DICOMweb.")
        print("DICOMweb response body:",response_dataset)

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

        # print("Instances fetched from PACS:", instances)
        # print(f"Number of instances retrieved: {len(instances)}")

        if len(instances) == 0:
            raise ValueError(f"No instances found for StudyInstanceUID: {study_instance_uid}")
        
        io_sop_instance_uids = []
        sr_sop_instance_uids = []

        dataset_ids = []
        rulers_json_strings=[]

        # TODO: for testing only
        origin_filenames = ["20459516_20241220_IO_1_2.dcm"]
        
        origin_ds = None
        sr_ds = []

        for instance in instances:
            # 從巢狀字典中取得 Modality 的值 (例如: 'SR' 或 'IO')
            # 結構是 {'Value': ['SR'], 'vr': 'CS'} -> 我們需要 ['Value'] 列表中的第一個元素 [0]
            modality = instance.get('00080060')['Value'][0]
            
            # 同樣地，取得 SOPInstanceUID 的值
            sop_instance_uid = instance.get('00080018')['Value'][0]
            
            # 根據 Modality 的值，將 sop_instance_uid 加入對應的列表
            if modality == 'IO':
                # Get DICOM-IO from Orthanc
                # io_sop_instance_uids.append(sop_instance_uid)
                # origin_ds = await fetch_instance_by_sop(
                #     instance.get('0020000D')['Value'][0],
                #     instance.get('0020000E')['Value'][0],
                #     sop_instance_uid)

                origin_ds = client.retrieve_instance(
                    study_instance_uid=instance.get('0020000D')['Value'][0],
                    series_instance_uid=instance.get('0020000E')['Value'][0],
                    sop_instance_uid=sop_instance_uid)
                
            elif modality == 'SR':
                sr_sop_instance_uids.append(sop_instance_uid)
                sr_ds_s = client.retrieve_instance(
                    study_instance_uid=instance.get('0020000D')['Value'][0],
                    series_instance_uid=instance.get('0020000E')['Value'][0],
                    sop_instance_uid=sop_instance_uid)
                dataset_ids.append(sr_ds_s.get((0x7777,0x11)).value)
                rulers_json_strings.append(sr_ds_s.get((0x7777,0x12)).value)

        # 呼叫函式來產生資料結構
        generated_datasets, generated_sources, generated_paths = generate_data_structure(dataset_uids=dataset_ids, filenames=origin_filenames)
        # print("dataset_ids:", dataset_ids)
        # print("filenames:", origin_filenames)
        # print("==================================")
        # print("generated_datasets:", generated_datasets)
        # print("generated_sources:", generated_sources)
        # print("generated_paths:", generated_paths)

        # --- 處理尺規 (Measurement) ---

        all_ruler_tools = []
        all_ruler_labels = {}

        # 1. 遍歷從 SR 檔案讀取到的每一個尺規 JSON 字串
        for ruler_json in rulers_json_strings:
            # 2. 將 JSON 字串解析成 Python 字典
            ruler_data_dict = json.loads(ruler_json)

            # 3. 將解析出來的 tools 和 labels 添加到我們的匯總列表中
            if 'tools' in ruler_data_dict:
                # 使用 extend 將一個列表的所有元素加入另一個列表
                all_ruler_tools.extend(ruler_data_dict['tools'])

            if 'labels' in ruler_data_dict:
                # 使用 update 將一個字典合併到另一個字典
                all_ruler_labels.update(ruler_data_dict['labels'])

        
        # 4. 使用合併後的資料建立 Rulers Pydantic 模型
        #    Pydantic 會自動驗證並將 dict 轉換為 Ruler 和 ToolLabel 物件
        final_rulers_model = Rulers(tools=all_ruler_tools, labels=all_ruler_labels)

        # 為了建立完整的 ViewerSession，我們需要一些假的 "tools" 和 "layout" 資料
        fake_tools = Tools(
                crosshairs={"position": (0, 0, 0)},
                paint={"activeSegmentGroupID": None, "activeSegment": 1, "brushSize": 4},
                crop={},
                current="Ruler",
                polygons={"tools": [], "labels": {}},
                rectangles={"tools": [], "labels": {}},
                rulers=final_rulers_model
            )
        
        fake_layout = Layout(name="Axial Only", direction="H", items=["Axial"])

        # 將所有部分組合到 ViewerSession 模型中

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
            primarySelection=dataset_ids[-1] # 通常會選取最後一個或某個特定的 UID
        )

        # save
        json_output = viewer_session.model_dump_json(indent=4, by_alias=True)

        # 儲存 manifest.json (可選步驟，主要是在記憶體中處理)
        with open("manifest.json", "w", encoding="utf-8") as f:
            f.write(json_output)

        print("\n--- 已產生 manifest.json ---")

        # --- NEW: Convert pydicom dataset to bytes and prepare for zip ---

        # 1. Convert the in-memory pydicom dataset (origin_ds) to raw bytes.
        dicom_buffer = io.BytesIO()
        # write_like_original=False ensures a standard, compliant DICOM file is written.
        pydicom.dcmwrite(dicom_buffer, origin_ds, write_like_original=False)
        dicom_buffer.seek(0)  # Rewind the buffer to the beginning
        dicom_file_bytes = dicom_buffer.getvalue()

        # 2. Create the dictionary mapping the filename to its byte content.
        #    Your current logic handles one file, so we get the first filename.
        dicom_data_map = {
            origin_filenames[0]: dicom_file_bytes
        }

        # 3. Call the new function with the in-memory data
        zip_bytes = create_volview_zip_from_memory(
            manifest_content=json_output,
            dataset_file_path=generated_paths,
            dicom_files_in_memory=dicom_data_map
        )
        
        print(f"Generated in-memory zip file of size: {len(zip_bytes)} bytes")

        # Return the zip bytes directly in the response
        # FastAPI will handle the headers correctly.
        return Response(content=zip_bytes, media_type="application/zip")
    
    except Exception as e:
        print(f"Error loading session: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)