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
import vtk
from vtk.util import numpy_support

# ✅ FIXED IMPORTS (IMPORTANT)
from .models import Manifest
from . import settings
from .sr_generator import SRGenerator

from .utils1 import (
    DotDict,
    get_filepath_for_subject,
    read_file_from_zip,
    create_empty_sr,
    update_general_module,
    update_patient_module,
    update_sr_content_module,
    update_private_tags,
)

from .utils2 import (
    Rulers,
    Tools,
    Layout,
    ViewerSession,
    generate_data_structure,
    create_volview_zip_from_memory,
)

from dicomweb_client.api import DICOMwebClient


# ------------------- Config -------------------
dicomweb_url = settings.DICOMWEB_URL
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
        zip_data = await request.body()
        if not zip_data:
            raise ValueError("No zip data received")

        zip_file_in_memory = io.BytesIO(zip_data)
        manifest_string = read_file_from_zip(zip_file_in_memory, "manifest.json")
        manifest = DotDict.from_dict(json.loads(manifest_string))

        path_value = list(manifest["datasetFilePath"].values())[0]
        subject = read_file_from_zip(zip_file_in_memory, path_value)
        ds = pydicom.dcmread(io.BytesIO(subject))

        study_instance_uid = ds.get("StudyInstanceUID")
        patient_id = ds.get("PatientID")

        subjects = [dataset for dataset in manifest["datasets"]]
        measurements = [ruler for ruler in manifest["tools"]["rulers"]["tools"]]

        series_instance_UID = await get_series_uid()
        await delete_orthanc_series(patient_id, study_instance_uid, series_instance_UID)

        for subject in subjects:
            filepath = get_filepath_for_subject(subject, manifest)
            subject_ds = pydicom.dcmread(
                io.BytesIO(read_file_from_zip(zip_file_in_memory, filepath))
            )

            for measurement in measurements:
                if subject["id"] != measurement["imageID"]:
                    continue

                sr_ds = create_empty_sr()
                sr_ds = update_general_module(sr_ds, subject_ds)
                sr_ds = update_patient_module(sr_ds, subject_ds)
                sr_ds = update_private_tags(sr_ds, measurement)
                sr_ds.SeriesInstanceUID = series_instance_UID

                client.store_instances(datasets=[sr_ds])

        return JSONResponse(content={"success": True}, status_code=200)

    except Exception as e:
        return JSONResponse(
            content={"success": False, "error": str(e)}, status_code=500
        )


# ------------------- /api/load -------------------
@app.post("/api/load")
async def load_session(request: Request):
    try:
        study_instance_uid = (await request.json()).get("StudyInstanceUID")
        if not study_instance_uid:
            raise ValueError("StudyInstanceUID required")

        instances = client.search_for_instances(
            study_instance_uid=study_instance_uid
        )
        if not instances:
            raise ValueError("No instances found")

        dataset_uids = []
        subject_files = {}

        for instance in instances:
            ds = client.retrieve_instance(
                study_instance_uid=instance["0020000D"]["Value"][0],
                series_instance_uid=instance["0020000E"]["Value"][0],
                sop_instance_uid=instance["00080018"]["Value"][0],
            )

            dataset_id = (
                f"{ds.SeriesInstanceUID}.1{ds.Rows}{ds.Columns}"
                f"{ds.SeriesDate}.1D000000S0D000000S0D000000S0D000000S1D000000S0D000000"
            )
            dataset_uids.append(dataset_id)

            filename = f"{ds.PatientID}-{ds.StudyDate}-{ds.InstanceNumber}.dcm"
            subject_files[filename] = [
                ds.SOPInstanceUID,
                ds.SeriesInstanceUID,
                ds.StudyInstanceUID,
            ]

        generated_datasets, generated_sources, generated_paths = generate_data_structure(
            dataset_uids, subject_files
        )

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
            primarySelection=dataset_uids[-1],
        )

        zip_bytes = create_volview_zip_from_memory(
            viewer_session, generated_paths, subject_files, client
        )

        return Response(content=zip_bytes, media_type="application/zip")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------- Series helpers -------------------
async def get_series_uid():
    series = client.search_for_series(
        search_filters={"SeriesDescription": "Measurement Report"}
    )
    if series:
        return series[0]["0020000E"]["Value"][0]
    return generate_uid()


ORTHANC_BASE_URL = "http://localhost:8080"


async def delete_orthanc_series(patient_id, study_uid, series_uid):
    concat = f"{patient_id}|{study_uid}|{series_uid}".encode()
    orthanc_id = "-".join(
        hashlib.sha1(concat).hexdigest()[i : i + 8]
        for i in range(0, 40, 8)
    )

    async with httpx.AsyncClient() as client:
        await client.delete(f"{ORTHANC_BASE_URL}/series/{orthanc_id}")
        return {"success": True}


# ------------------- Manifest ↔ SR -------------------
@app.post("/manifest_to_dicom_sr")
async def manifest_to_dicom_sr(manifest: Manifest):
    gen = SRGenerator(manifest)
    ds = gen.generate()
    buffer = io.BytesIO()
    ds.save_as(buffer)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/dicom",
        headers={
            "Content-Disposition": f"attachment; filename={manifest.study_instance_uid}_sr.dcm"
        },
    )


@app.post("/dicom_sr_to_manifest")
async def dicom_sr_to_manifest(request: Request):
    dicom_bytes = await request.body()
    ds = pydicom.dcmread(io.BytesIO(dicom_bytes))
    raw = ds[(0x0043, 0x1010)].value
    manifest = json.loads(gzip.decompress(raw).decode())
    return JSONResponse(content=manifest)


# ------------------- CORS -------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
