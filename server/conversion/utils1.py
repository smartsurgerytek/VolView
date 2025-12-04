import pydicom
import datetime

from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import generate_uid
from pynetdicom.sop_class import SegmentationStorage
from pynetdicom.sop_class import BasicTextSRStorage
import json

class DotDict(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

    @staticmethod
    def from_dict(d):
        if not isinstance(d, dict):
            return d
        new_dict = DotDict()
        for k, v in d.items():
            new_dict[k] = DotDict.from_dict(v)
        return new_dict

def create_empty_sr():
    sr_ds = FileDataset(None, {}, file_meta=pydicom.Dataset(), preamble=b"\0" * 128)

    # File Meta Information (0002,xxxx)
    sr_ds.file_meta.FileMetaInformationVersion = b'\x00\x01'
    sr_ds.file_meta.MediaStorageSOPClassUID = '1.2.840.10008.5.1.4.1.1.88.22' # Enhanced SR
    sr_ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    sr_ds.file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian
    sr_ds.file_meta.ImplementationClassUID = '1.2.826.0.1.3680043.8.498.79718335388386899263523456779912018987' # Should make it unchangeable to represent the manufactor is us
    sr_ds.file_meta.ImplementationVersionName = 'SST-1.0.0'

    # Basic DICOM property
    sr_ds.SOPClassUID = '1.2.840.10008.5.1.4.1.1.88.22' # Enhanced SR
    sr_ds.SOPInstanceUID = sr_ds.file_meta.MediaStorageSOPInstanceUID
    sr_ds.Modality = 'SR'
    sr_ds.SpecificCharacterSet = 'ISO_IR 192' # UTF-8

    # Content Date and Time
    now = datetime.datetime.now()
    sr_ds.ContentDate = now.strftime('%Y%m%d')
    sr_ds.ContentTime = now.strftime('%H%M%S')

    print("Empty DICOM SR Created")
    return sr_ds

def update_general_module(sr_ds, original_ds):
    # Study Data
    sr_ds.StudyInstanceUID = original_ds.get('StudyInstanceUID')
    sr_ds.StudyID = original_ds.get('StudyID')
    sr_ds.StudyDate = original_ds.get('StudyDate')
    sr_ds.StudyTime = original_ds.get('StudyTime')
    ## sr_ds.StudyInstanceUID = 1

    # Series Data : We will create new Series for SR file
    # sr_ds.SeriesInstanceUID = generate_uid()
    sr_ds.SeriesDate = sr_ds.ContentDate
    sr_ds.SeriesTime = sr_ds.ContentTime
    sr_ds.SeriesDescription = 'Measurement Report'

    ## sr_ds.SeriesNumber = 1

    # Instance Number
    ## sr_ds.InstanceNumber = 1

    sr_ds.ReferencedSOPInstanceUID = original_ds.get('SOPInstanceUID')

    # Others
    sr_ds.AccessionNumber = original_ds.get('AccessionNumber')
    sr_ds.Manufacturer = 'Unspecified'
    sr_ds.ManufacturerModelName = 'Unspecified'
    sr_ds.ReferringPhysicianName = original_ds.get('ReferringPhysicianName')

    return sr_ds

def update_patient_module(sr_ds, original_ds):

    # Patient Data
    sr_ds.PatientName = original_ds.get('PatientName')
    sr_ds.PatientID = original_ds.get('PatientID')
    sr_ds.PatientBirthDate = original_ds.get('PatientBirthDate')
    sr_ds.PatientSex = original_ds.get('PatientSex')
    sr_ds.Age = original_ds.get('Age')

    return sr_ds

def update_sr_content_module(sr_ds):

    # SR Document Title (Code Sequence) - Using LO for a descriptive string title
    # In a real SR, this would ideally be a Code Sequence (0040,A040)
    # Using LO (Long String) as a placeholder for a descriptive title that exceeds CS length
    sr_ds.add_new(0x0040A040, 'LO', 'Measurement Report') # Example

    # Completion Flag (CS)
    sr_ds.CompletionFlag = 'COMPLETE' # Or PARTIAL

    # Verification Flag (CS)
    sr_ds.VerificationFlag = 'UNVERIFIED' # Or VERIFIED

    # Content Sequence (SQ) - This is where the actual SR content goes
    # This is a complex structure and would need to be built based on the SR template
    sr_ds.add_new(0x0040A730, 'SQ', []) # Content Sequence

    return sr_ds

def update_private_tags(sr_ds, measurement_data):

    group_number = 0x7777
    creator_id = "SST_VOLVIEW_METADATA"

    dataset_ids_element = 0x11
    measurement_rulers = 0x12

    ### Creator Id
    sr_ds.add_new((group_number, 0x0010), 'LO', creator_id)

    ### Dataset ID
    ### sr_ds.add_new((group_number, dataset_ids_element), 'UT', dataset_ids)

    ### Measurement
    sr_ds.add_new((group_number, measurement_rulers), 'UT', json.dumps(measurement_data))

    return sr_ds


import zipfile
import io

def read_file_from_zip(zip_path, internal_path):
    """
    從指定的 ZIP 檔案中讀取一個內部檔案的二進位內容。

    Args:
        zip_path (str): ZIP 檔案的系統路徑。
        internal_path (str): ZIP 檔案內部的檔案相對路徑。

    Returns:
        bytes: 檔案的二進位內容。
        None: 如果 ZIP 檔案或內部檔案不存在。
    """
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # zf.read() 會回傳檔案的 raw bytes
            file_bytes = zf.read(internal_path)
            return file_bytes
    except FileNotFoundError:
        print(f"錯誤：找不到 ZIP 檔案 '{zip_path}'")
        return None
    except KeyError:
        print(f"錯誤：在 ZIP 檔案中找不到路徑 '{internal_path}'")
        return None
        
def get_filepath_for_subject(subject, manifest):
    """
    根據 subject 物件，從 manifest 中查找並回傳對應的 DICOM 檔案路徑。

    Args:
        subject (dict or DotDict): manifest['datasets'] 中的一個元素。
        manifest (DotDict): 已解析的 manifest.json 物件。

    Returns:
        str: 找到的檔案路徑，例如 'data/3/20459516_20241220_IO_1_1.dcm'。
        None: 如果在查找過程中任何步驟失敗。
    """
    try:
        # 為了方便快速查找，先將 dataSources 轉換成以 id 為 key 的字典
        data_sources_map = {ds['id']: ds for ds in manifest.dataSources}

        # 步驟 1: 拿 subject 的 dataSourceId 找到 "collection" source
        collection_source = data_sources_map[subject['dataSourceId']]

        # 步驟 2: 從 "collection" source 取得 "file" source 的 ID
        file_source_id = collection_source['sources'][0]

        # 步驟 3: 拿 file_source_id 找到 "file" source
        file_source = data_sources_map[file_source_id]

        # 步驟 4: 從 "file" source 取得 fileId
        file_id = file_source['fileId']

        # 步驟 5: 使用 fileId (需轉成字串) 取得最終的檔案路徑
        filepath = manifest.datasetFilePath[str(file_id)]
        
        return filepath
        
    except (KeyError, IndexError):
        # 如果任何一個 ID 找不到 (KeyError) 或 sources 列表為空 (IndexError)，
        # 就會捕捉到例外並回傳 None。
        return None
