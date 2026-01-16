import os
import io
import zipfile
from typing import List, Dict, Tuple, Any, Optional

import httpx
from pydantic import BaseModel, Field

import settings

# --- Sub-tools and common models ---

class FrameOfReference(BaseModel):
    """Model defining a coordinate system"""
    planeNormal: Tuple[int, int, int]
    planeOrigin: Tuple[int, int, int]

class ToolLabel(BaseModel):
    """Common model defining a tool label"""
    labelName: str
    color: str
    strokeWidth: int

class FillableToolLabel(ToolLabel):
    """Extended from ToolLabel, adds fill color"""
    fillColor: str

# --- Detailed models for each tool ---

class Crosshairs(BaseModel):
    position: Tuple[int, int, int]

class Paint(BaseModel):
    activeSegmentGroupID: Optional[Any]  # null in JSON
    activeSegment: Optional[int] = None
    brushSize: int

class CropBounds(BaseModel):
    """Cropping bounds for a single image"""
    Sagittal: Tuple[float, float]
    Coronal: Tuple[float, float]
    Axial: Tuple[float, float]

class Ruler(BaseModel):
    """Model defining a single ruler"""
    imageID: str
    frameOfReference: FrameOfReference
    slice_val: int = Field(alias='slice')  # 'slice' is a Python reserved word, handled via alias
    placing: bool
    color: str
    strokeWidth: int
    name: str
    firstPoint: Tuple[float, float, float]
    secondPoint: Tuple[float, float, float]
    id: str
    label: str
    labelName: str

class Polygons(BaseModel):
    tools: List[Any]  # empty array in JSON
    labels: Dict[str, ToolLabel]

class Rectangles(BaseModel):
    tools: List[Any]  # empty array in JSON
    labels: Dict[str, FillableToolLabel]

class Rulers(BaseModel):
    tools: List[Ruler]
    labels: Dict[str, ToolLabel]

class Tools(BaseModel):
    """Top-level model combining all tools"""
    crosshairs: Crosshairs
    paint: Paint
    crop: Dict[str, CropBounds]  # Key is dataset ID
    current: str
    polygons: Polygons
    rectangles: Rectangles
    rulers: Rulers

# --- Data Source ---

class Dataset(BaseModel):
    id: str
    dataSourceId: int

class DataSource(BaseModel):
    id: int
    type: str
    # Use Optional to indicate some fields may not exist
    sources: Optional[List[int]] = None
    fileId: Optional[int] = None
    fileType: Optional[str] = None

# --- Layout ---

class Layout(BaseModel):
    name: str
    direction: str
    items: List[str]

# --- Viewer Session ---

class ViewerSession(BaseModel):
    version: str
    datasets: List[Dataset]
    dataSources: List[DataSource]
    datasetFilePath: Dict[str, str]
    labelMaps: List[Any]  # TODO: ignore segmentation for now
    tools: Tools
    layout: Layout
    views: List[Any]  # views can be empty
    parentToLayers: List[Any]  # empty
    primarySelection: str

    class Config:
        # Pydantic v2 handles aliases by default, but this makes it explicit
        populate_by_name = True

def generate_data_structure(
    dataset_uids: List[str],
    filenames: List[str]
) -> Tuple[List[Dataset], List[DataSource], Dict[str, str]]:
    """
    Generate the data structures required for the manifest
    based on DICOM UIDs and filename lists.

    Args:
        dataset_uids: A list of DICOM Series Instance UIDs.
        filenames: A list of corresponding filenames.

    Returns:
        A tuple containing three elements:
        1. datasets: A list of objects conforming to the Pydantic `Dataset` model.
        2. data_sources: A list of objects conforming to the Pydantic `DataSource` model.
        3. dataset_file_path: A dictionary mapping file IDs to file paths.
    """
    if len(dataset_uids) != len(filenames):
        raise ValueError("The UID list and filename list must have the same length.")

    datasets: List[Dataset] = []
    data_sources: List[DataSource] = []
    dataset_file_path: Dict[str, str] = {}

    # This counter is key to generating unique IDs
    next_id = 1

    for uid, filename in zip(dataset_uids, filenames):
        # 1. Generate a sequence of IDs for each file
        collection_id = next_id
        source_id = next_id + 1
        file_id = next_id + 2

        # 2. Create Dataset object and link it to collection_id
        dataset_obj = Dataset(id=uid, dataSourceId=collection_id)
        datasets.append(dataset_obj)

        # 3. Create two DataSource objects

        # a. "file" type, linked to file_id
        file_source = DataSource(
            id=source_id,
            type="file",
            fileId=file_id,
            fileType="application/dicom"
        )
        data_sources.append(file_source)

        # b. "collection" type, linked to source_id
        collection_source = DataSource(
            id=collection_id,
            type="collection",
            sources=[source_id]
        )

        data_sources.append(collection_source)

        # 4. Build file path, using file_id as the key
        path = f"data/{file_id}/{filename}"
        dataset_file_path[str(file_id)] = path

        # 5. Update counter for the next file
        next_id += 3

    return datasets, data_sources, dataset_file_path

async def create_volview_zip_from_memory(
    viewer_session: ViewerSession,
    generated_paths: {Dict[str, str]},
    subject_files: Dict[str, list],
    client,
    is_manifest_from_sr: bool = False
) -> bytes:
    """
    Generate a ZIP file required by VolView from a ViewerSession object
    and a dictionary of DICOM files.

    Args:
        viewer_session: An object conforming to the Pydantic `ViewerSession` model.
        dicom_files: A dictionary where keys are filenames and values are
                     the corresponding DICOM file bytes.

    Returns:
        The generated ZIP file content as bytes.
    """
    
    zip_buffer = io.BytesIO()

    try:
        print("Creating ZIP file in memory...")
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            
            # if is_manifest_from_sr:
            #     # If the manifest is from SR, assume viewer_session is already a JSON string
            #     json_output = viewer_session
            # else:
            json_output = viewer_session.model_dump_json(indent=4, by_alias=True)
            zf.writestr("manifest.json", json_output)
        
            for path in generated_paths.values():
                print("Generated file path:", path)
                filename = path.split('/')[-1]
        
                # Get instance from PACS
                subject_ds = client.retrieve_instance(
                    study_instance_uid=subject_files[filename][2],
                    series_instance_uid=subject_files[filename][1],
                    sop_instance_uid=subject_files[filename][0],                    
                )
        
                with io.BytesIO() as dcm_buffer:
                    subject_ds.save_as(dcm_buffer, write_like_original=True)
                    zf.writestr(path, dcm_buffer.getvalue())
                    
            # fetch segmentation files if any
            segmenation_zip = await fetch_segmentation_zip(
                study_uid=subject_files[filename][2]
            )
            with zipfile.ZipFile(segmenation_zip, "r") as seg_zip:
                for entry in seg_zip.infolist():
                    if entry.filename.startswith("labels/"):
                        zf.writestr(
                            entry.filename,
                            seg_zip.read(entry.filename)
                    )

        zip_bytes = zip_buffer.getvalue()
        
        print(f"ZIP file created in memory. Size: {len(zip_bytes)} bytes")

        return zip_bytes

    except Exception as e:
        print(f"Error creating zip file: {e}")
        raise e

async def fetch_segmentation_zip(
    study_uid: str
) -> bytes:
    try:
        print("---------------ABPAPI_URL---------", settings.ABPAPI_URL)

        async with httpx.AsyncClient(verify=False) as client:
            seg_resp = await client.get(
                f"{settings.ABPAPI_URL}/segmentation/{study_uid}"
            )
            seg_resp.raise_for_status()

        return io.BytesIO(seg_resp.content)

    except Exception as e:
        print(f"Error fetching segmentation zip: {e}")
        raise e