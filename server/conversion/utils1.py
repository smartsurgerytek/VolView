import pydicom
import datetime

from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import generate_uid
from pynetdicom.sop_class import SegmentationStorage
from pynetdicom.sop_class import BasicTextSRStorage

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
    sr_ds.StudyID = original_ds.get('StudyID')
    sr_ds.StudyDate = original_ds.get('StudyDate')
    sr_ds.StudyTime = original_ds.get('StudyTime')
    sr_ds.StudyInstanceUID = original_ds.get('StudyInstanceUID')

    # Series Data : We will create new Series for SR file
    sr_ds.SeriesInstanceUID = generate_uid()
    sr_ds.SeriesDate = sr_ds.ContentDate
    sr_ds.SeriesTime = sr_ds.ContentTime

    ## sr_ds.SeriesNumber = 1

    # Instance Number
    ## sr_ds.InstanceNumber = 1

    # Referenced SOP Instance UID
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

def update_private_tags(sr_ds):


    return sr_ds