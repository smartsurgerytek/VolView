import json
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

def create_volview_zip(
    manifest_content: str,
    dataset_file_path: Dict[str, str],
    origin_local_files: List[str],
    output_zip_filename: str
):
    """
    將 manifest.json 和原始 DICOM 檔案打包成一個 volview zip 檔案。

    Args:
        manifest_content: manifest.json 的檔案內容 (字串)。
        dataset_file_path: 從 generate_data_structure 產生的路徑字典。
        origin_local_files: 本地原始 DICOM 檔案的路徑列表。
        output_zip_filename: 輸出的 zip 檔案名稱。
    """
    print("\n--- 開始建立 ZIP 壓縮檔 ---")
    
    # 建立一個從 "檔名" 到 "在ZIP中的完整路徑" 的映射
    # 例如: {"20459516...dcm": "data/3/20459516...dcm"}
    filename_to_zip_path = {os.path.basename(p): p for p in dataset_file_path.values()}

    # 使用 'w' 模式建立一個新的 zip 檔案
    # zipfile.ZIP_DEFLATED 是標準的壓縮模式
    with zipfile.ZipFile(output_zip_filename, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 1. 將 manifest.json 內容寫入 zip 檔案的根目錄
        zf.writestr('manifest.json', manifest_content)
        print(f"已將 manifest.json 加入 '{output_zip_filename}'")

        # 2. 遍歷本地的原始檔案列表
        for local_filepath in origin_local_files:
            base_filename = os.path.basename(local_filepath)
            
            # 根據檔名查找它在 zip 中應該被存放的路徑
            if base_filename in filename_to_zip_path:
                destination_path = filename_to_zip_path[base_filename]
                
                # 將本地檔案寫入 zip，並指定其在 zip 內的路徑和名稱
                zf.write(local_filepath, destination_path)
                print(f"已將 '{local_filepath}' 加入壓縮檔，路徑為 '{destination_path}'")
            else:
                print(f"警告：在 manifest 中找不到檔案 '{local_filepath}' 的對應路徑，已跳過。")

    print(f"\n 成功建立壓縮檔: '{output_zip_filename}'")

# def create_volview_zip_in_memory(
#     manifest_content: str,
#     dataset_file_path: Dict[str, str],
#     origin_local_files: List[str],
# ) -> bytes:
#     """
#     Creates a volview-compatible zip archive directly in memory.

#     Args:
#         manifest_content: The manifest.json content as a string.
#         dataset_file_path: A dictionary mapping file IDs to their paths within the zip.
#         origin_local_files: A list of local file paths for the DICOM files to include.

#     Returns:
#         The complete zip archive as a bytes object.
#     """
#     print("\n--- Starting in-memory ZIP creation ---")
    
#     # Use io.BytesIO to create an in-memory binary stream
#     zip_buffer = io.BytesIO()

#     # Create a mapping from filename to its full path inside the zip
#     filename_to_zip_path = {os.path.basename(p): p for p in dataset_file_path.values()}

#     # Use 'w' mode to write to the memory buffer
#     with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
#         # 1. Write the manifest.json content to the root of the zip archive
#         zf.writestr('manifest.json', manifest_content)
#         print("Added manifest.json to in-memory zip")

#         # 2. Iterate through the local files that need to be added
#         for local_filepath in origin_local_files:
#             base_filename = os.path.basename(local_filepath)

#             print(f"Processing local file: {local_filepath}")
            
#             print(f"filename_to_zip_path keys: {list(filename_to_zip_path.keys())}")

#             if base_filename in filename_to_zip_path:
#                 destination_path = filename_to_zip_path[base_filename]

#                 print(f"destination path in zip: {destination_path}")
                
#                 # Write the local file to the specified path within the zip archive
#                 zf.write(local_filepath, destination_path)
#                 print(f"Added '{local_filepath}' to zip at path '{destination_path}'")
#             else:
#                 print(f"Warning: Could not find a path for '{local_filepath}' in the manifest. Skipping.")
    
#     print("--- In-memory ZIP creation complete ---")
    
#     # Return the bytes content of the buffer
#     return zip_buffer.getvalue()

def create_volview_zip_from_memory(
    manifest_content: str,
    dataset_file_path: Dict[str, str],
    dicom_files_in_memory: Dict[str, bytes]
) -> bytes:
    """
    Creates a volview-compatible zip archive using in-memory file content.

    Args:
        manifest_content: The manifest.json content as a string.
        dataset_file_path: A dictionary mapping file IDs to their paths within the zip.
        dicom_files_in_memory: A dictionary where the key is the original filename
                               (e.g., "image.dcm") and the value is the raw byte
                               content of that DICOM file.

    Returns:
        The complete zip archive as a bytes object.
    """
    print("\n--- Starting in-memory ZIP creation from memory objects ---")
    
    zip_buffer = io.BytesIO()

    # Create a mapping from filename to its full path inside the zip
    # e.g., {"image.dcm": "data/3/image.dcm"}
    filename_to_zip_path = {os.path.basename(p): p for p in dataset_file_path.values()}

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 1. Write the manifest.json content
        zf.writestr('manifest.json', manifest_content)
        print("Added manifest.json to in-memory zip")

        # 2. Iterate through the in-memory files provided
        for filename, file_bytes in dicom_files_in_memory.items():
            if filename in filename_to_zip_path:
                destination_path = filename_to_zip_path[filename]
                
                # Use zf.writestr() to add the byte content directly
                # to the specified path within the zip archive.
                zf.writestr(destination_path, file_bytes)
                print(f"Added in-memory file '{filename}' to zip at path '{destination_path}'")
            else:
                print(f"Warning: Could not find a path for '{filename}' in the manifest. Skipping.")
    
    print("--- In-memory ZIP creation complete ---")
    
    return zip_buffer.getvalue()