import os
import io
import zipfile
from typing import List, Dict, Tuple, Any, Optional

from pydantic import BaseModel, Field

# --- 子工具與通用模型 ---

class FrameOfReference(BaseModel):
    """定義座標系的模型"""
    planeNormal: Tuple[int, int, int]
    planeOrigin: Tuple[int, int, int]

class ToolLabel(BaseModel):
    """定義工具標籤的通用模型"""
    labelName: str
    color: str
    strokeWidth: int

class FillableToolLabel(ToolLabel):
    """擴充自 ToolLabel，增加了填充色"""
    fillColor: str

# --- 各個工具 (Tools) 的詳細模型 ---

class Crosshairs(BaseModel):
    position: Tuple[int, int, int]

class Paint(BaseModel):
    activeSegmentGroupID: Optional[Any] # JSON 中為 null
    activeSegment: int
    brushSize: int

class CropBounds(BaseModel):
    """單一影像的裁切邊界"""
    Sagittal: Tuple[float, float]
    Coronal: Tuple[float, float]
    Axial: Tuple[float, float]

class Ruler(BaseModel):
    """定義單一把尺規的模型"""
    imageID: str
    frameOfReference: FrameOfReference
    slice_val: int = Field(alias='slice') # 'slice' is python reserved words, process with alias
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
    tools: List[Any] # JSON 中為空陣列
    labels: Dict[str, ToolLabel]

class Rectangles(BaseModel):
    tools: List[Any] # JSON 中為空陣列
    labels: Dict[str, FillableToolLabel]

class Rulers(BaseModel):
    tools: List[Ruler]
    labels: Dict[str, ToolLabel]

class Tools(BaseModel):
    """組合所有工具的頂層模型"""
    crosshairs: Crosshairs
    paint: Paint
    crop: Dict[str, CropBounds] # Key 是 dataset 的 ID
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
    # 使用 Optional 來表示某些欄位可能不存在
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
    labelMaps: List[Any] # TODO: ignore segmentation at this time
    tools: Tools
    layout: Layout
    views: List[Any] # views can be empty
    parentToLayers: List[Any] # empty
    primarySelection: str

    class Config:
        # Pydantic V2 預設會處理 alias，但寫上可以更明確
        populate_by_name = True

def generate_data_structure(
    dataset_uids: List[str],
    filenames: List[str]
) -> Tuple[List[Dataset], List[DataSource], Dict[str, str]]:
    """
    根據 DICOM UID 和檔名列表，產生 manifest 所需的資料結構。

    Args:
        dataset_uids: 一個包含 DICOM Series Instance UIDs 的列表。
        filenames: 一個包含對應檔名的列表。

    Returns:
        一個包含三個元素的元組：
        1. datasets: 符合 Pydantic `Dataset` 模型的物件列表。
        2. data_sources: 符合 Pydantic `DataSource` 模型的物件列表。
        3. dataset_file_path: 一個包含檔案路徑的字典。
    """
    if len(dataset_uids) != len(filenames):
        raise ValueError("UID 列表和檔名列表的長度必須相同。")

    datasets: List[Dataset] = []
    data_sources: List[DataSource] = []
    dataset_file_path: Dict[str, str] = {}

    # 這個計數器是產生唯一 ID 的關鍵
    next_id = 1

    for uid, filename in zip(dataset_uids, filenames):
        # 1. 為每個檔案產生一組連續的 ID
        collection_id = next_id
        source_id = next_id + 1
        file_id = next_id + 2

        # 2. 建立 Dataset 物件，並連結到 collection_id
        dataset_obj = Dataset(id=uid, dataSourceId=collection_id)
        datasets.append(dataset_obj)

        # 3. 建立兩個 DataSource 物件

        # a. "file" 型別，連結到 file_id
        file_source = DataSource(
            id=source_id,
            type="file",
            fileId=file_id,
            fileType="application/dicom"
        )
        data_sources.append(file_source)

        # b. "collection" 型別，連結到 source_id
        collection_source = DataSource(
            id=collection_id,
            type="collection",
            sources=[source_id]
        )

        data_sources.append(collection_source)

        # 4. 建立檔案路徑，並以 file_id 作為 key
        path = f"data/{file_id}/{filename}"
        dataset_file_path[str(file_id)] = path

        # 5. 更新計數器，為下一個檔案準備
        next_id += 3

    return datasets, data_sources, dataset_file_path

def create_volview_zip_from_memory(
    viewer_session: ViewerSession,
    generated_paths: {Dict[str, str]},
    subject_files: Dict[str, list],
    client
) -> bytes:
    """
    根據 ViewerSession 物件和 DICOM 檔案字典，產生 VolView 所需的 ZIP 檔案。

    Args:
        viewer_session: 一個符合 Pydantic `ViewerSession` 模型的物件。
        dicom_files: 一個字典，鍵為檔名，值為對應的 DICOM 檔案位元組內容。

    Returns:
        產生的 ZIP 檔案內容，型別為 bytes。
    """
    
    zip_buffer = io.BytesIO()

    try:
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            
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

        zip_bytes = zip_buffer.getvalue()
        
        print(f"ZIP file created in memory. Size: {len(zip_bytes)} bytes")

        return zip_bytes

    except Exception as e:
        print(f"Error creating zip file: {e}")
        raise e
