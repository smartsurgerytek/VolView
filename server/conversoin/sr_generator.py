from io import BytesIO
import pydicom
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import ExplicitVRLittleEndian
from pydicom.uid import generate_uid
from models import Shape, Manifest

ENHANCED_SR_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.88.22"
TRANSFER_SYNTAX = ExplicitVRLittleEndian
IMPLEMENTATIONVERSION = "SRGenV1.0"

class SRGenerator:
    def __init__(self, manifest: Manifest):
        self.manifest = manifest

    def build_file_meta(self) -> Dataset:
        file_meta = Dataset()
        file_meta.MediaStorageSOPClassUID = ENHANCED_SR_SOP_CLASS_UID
        file_meta.MediaStorageSOPInstanceUID = generate_uid()
        file_meta.TransferSyntaxUID = TRANSFER_SYNTAX
        file_meta.ImplementationClassUID = generate_uid()
        file_meta.ImplementationVersionName = IMPLEMENTATIONVERSION
        return file_meta

    def generate(self) -> FileDataset:
        meta = self.build_file_meta()
        ds = FileDataset("output_sr.dcm", {}, file_meta=meta, preamble=b"\0" * 128)
        ds.is_little_endian = True
        ds.is_implicit_VR = False

        self._add_study_series_info(ds, meta)
        self._add_equipment_info(ds)
        self._add_patient_info(ds)
        
        self._add_measurement_report(ds)
        self._add_current_requested_procedure_evidence_sequence(ds, self.manifest.annotations)
        
        ds.CompletionFlag = "COMPLETE"
        ds.VerificationFlag = "UNVERIFIED"
        
        self._add_content_template_sequence(ds)

        measurements = self._generate_measurements_container()
        for annotation in self.manifest.annotations:
            mg = self._generate_measurement_group(annotation)
            if not hasattr(measurements, 'ContentSequence'):
                measurements.ContentSequence = []
            measurements.ContentSequence.append(mg)
                
        # Core SR sections
        ds.ContentSequence = [
            self._add_language_country_items(),
            self._add_observer_item(),
            self._add_procedure_item(),
            self._generate_image_library(self.manifest.annotations),
            measurements,
        ]
        
        return ds

    def _add_study_series_info(self, ds, file_meta):
        m = self.manifest
        # Study/Series/Instance metadata
        ds.SpecificCharacterSet = 'ISO_IR 192'
        ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
        ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID

        # ---------------------------------------------------
        # Study and Series Module
        # ---------------------------------------------------
        ds.StudyInstanceUID = m.study_instance_uid
        ds.SeriesInstanceUID = generate_uid()
        ds.SeriesDescription = 'pydicom-sr'
        ds.StudyID = m.study_id
        ds.SeriesNumber = "1"
        ds.InstanceNumber = "1"
        ds.ImageComments = "NOT FOR CLINICAL USE"

    def _add_equipment_info(self, ds):
        # Basic identification and modality info
        ds.AccessionNumber = 'T1131220068'
        ds.Modality = 'SR'
        ds.Manufacturer = 'Unspecified'
        # ds.ReferringPhysicianName = '¶¾¸t°¶'
        ds.ManufacturerModelName = 'Unspecified'
        ds.DeviceSerialNumber = "1"
        ds.SoftwareVersions = "0"
        ds.ContentQualification = "RESEARCH"

    def _add_patient_info(self, ds):
        m = self.manifest
        # Patient Module
        ds.PatientName = m.patient_name
        ds.PatientID = m.patient_id
        ds.PatientBirthDate = m.patient_birth_date
        ds.PatientSex = m.patient_sex

    def _add_measurement_container(self, ds):
        ds.ValueType = "CONTAINER"
        # Concept Name Code Sequence (Imaging Measurement Report)
        concept_name = Dataset()
        concept_name.CodeValue = "126000"
        concept_name.CodingSchemeDesignator = "DCM"
        concept_name.CodeMeaning = "Imaging Measurement Report"
        ds.ConceptNameCodeSequence = [concept_name]

        # Continuity of Content
        ds.ContinuityOfContent = "SEPARATE"

        # Performed Procedure Code Sequence (empty)
        ds.PerformedProcedureCodeSequence = []

    def _generate_referenced_SOP_sequence(self, ref_sop_class_uid, ref_sop_instance_uid):
        # Referenced SOP Sequence (the image being measured)
        ref_sop = Dataset()
        ref_sop.ReferencedSOPClassUID = ref_sop_class_uid  # Digital Intra-oral X-Ray Image Storage – For Processing
        ref_sop.ReferencedSOPInstanceUID = ref_sop_instance_uid

        return ref_sop

    def _generate_referenced_series_sequence(self, ref_series_instance_uid, ref_sop):
        # Referenced Series Sequence (contains the above SOP)
        ref_series = Dataset()
        ref_series.SeriesInstanceUID = ref_series_instance_uid
        ref_series.ReferencedSOPSequence = [ref_sop]

        return ref_series

    def _add_current_requested_procedure_evidence_sequence(self, ds, annotations):
        # Current Requested Procedure Evidence Sequence (contains all referenced series)
        evidence_items = []
        for annotation in annotations:
            ref_sop = self._generate_referenced_SOP_sequence(
                annotation.sop_class_uid,
                annotation.sop_instance_uid
            )
            ref_series = self._generate_referenced_series_sequence(
                annotation.series_instance_uid,
                ref_sop
            )
            
            evidence_item = Dataset()
            evidence_item.StudyInstanceUID = self.manifest.study_instance_uid
            evidence_item.ReferencedSeriesSequence = [ref_series]
            evidence_items.append(evidence_item)

        ds.CurrentRequestedProcedureEvidenceSequence = evidence_items
        
    def _add_content_template_sequence(self, ds):
        # ---------------------------------------------------
        # 3️⃣ Content Template Sequence (TID 1500)
        # ---------------------------------------------------
        template_item = Dataset()
        template_item.MappingResource = "DCMR"
        template_item.TemplateIdentifier = "1500"
        ds.ContentTemplateSequence = [template_item]

    # Helper to build code sequences easily
    def _generate_code(self, value, scheme, meaning, version=None):
        code = Dataset()
        code.CodeValue = value
        code.CodingSchemeDesignator = scheme
        if version:
            code.CodingSchemeVersion = version
        code.CodeMeaning = meaning
        return [code]

    def _add_language_country_items(self):
        # -------------------------------
        # Item #0 — Language of Content
        # -------------------------------
        language_item = Dataset()
        language_item.RelationshipType = "HAS CONCEPT MOD"
        language_item.ValueType = "CODE"
        language_item.ConceptNameCodeSequence = self._generate_code("121049", "DCM", "Language of Content Item and Descendants")
        language_item.ConceptCodeSequence = self._generate_code("eng", "RFC5646", "English")

        # Sub-item (country)
        country_item = Dataset()
        country_item.RelationshipType = "HAS CONCEPT MOD"
        country_item.ValueType = "CODE"
        country_item.ConceptNameCodeSequence = self._generate_code("121046", "DCM", "Country of Language")
        country_item.ConceptCodeSequence = self._generate_code("US", "ISO3166_1", "United States")

        language_item.ContentSequence = [country_item]
        return language_item

    def _add_observer_item(self):
        # -------------------------------
        # Item #1 — Person Observer Name
        # -------------------------------
        observer_item = Dataset()
        observer_item.RelationshipType = "HAS OBS CONTEXT"
        observer_item.ValueType = "PNAME"
        observer_item.ConceptNameCodeSequence = self._generate_code("121008", "DCM", "Person Observer Name")
        observer_item.PersonName = "unknown^unknown"
        return observer_item

    def _add_procedure_item(self):
        # -------------------------------
        # Item #2 — Procedure Reported
        # -------------------------------
        procedure_item = Dataset()
        procedure_item.RelationshipType = "HAS CONCEPT MOD"
        procedure_item.ValueType = "CODE"
        procedure_item.ConceptNameCodeSequence = self._generate_code("121058", "DCM", "Procedure reported")
        procedure_item.ConceptCodeSequence = self._generate_code("1", "99dcmjs", "Unknown procedure")
        return procedure_item

    def _add_measurement_report(self, ds):
        ds.ValueType = "CONTAINER"
        # Concept Name Code Sequence (Imaging Measurement Report)
        concept_name = Dataset()
        concept_name.CodeValue = "126000"
        concept_name.CodingSchemeDesignator = "DCM"
        concept_name.CodeMeaning = "Imaging Measurement Report"
        ds.ConceptNameCodeSequence = [concept_name]

        # Continuity of Content
        ds.ContinuityOfContent = "SEPARATE"

        # Performed Procedure Code Sequence (empty)
        ds.PerformedProcedureCodeSequence = []

    def _generate_measurements_container(self):
        # Top-level container "Imaging Measurements"
        measurements = Dataset()
        measurements.RelationshipType = "CONTAINS"
        measurements.ValueType = "CONTAINER"
        measurements.ConceptNameCodeSequence = self._generate_code("126010", "DCM", "Imaging Measurements")
        measurements.ContinuityOfContent = "SEPARATE"

        return measurements

    def _generate_image_library(self, annotations):
        # -------------------------------
        # Item #3 — Image Library
        # -------------------------------
        img_seq_items = []
        for annotation in annotations:
            ref_image = self._generate_referenced_SOP_sequence(
                annotation.sop_class_uid,
                annotation.sop_instance_uid
            )
            img_seq_item = Dataset()
            img_seq_item.ReferencedSOPSequence = [ref_image]
            img_seq_item.RelationshipType = "CONTAINS"
            img_seq_item.ValueType = "IMAGE"

            img_seq_items.append(img_seq_item)

        img_lib_group = Dataset()
        img_lib_group.RelationshipType = "CONTAINS"
        img_lib_group.ValueType = "CONTAINER"
        img_lib_group.ConceptNameCodeSequence = self._generate_code("126200", "DCM", "Image Library Group")
        img_lib_group.ContinuityOfContent = "SEPARATE"
        img_lib_group.ContentSequence = img_seq_items

        img_lib = Dataset()
        img_lib.RelationshipType = "CONTAINS"
        img_lib.ValueType = "CONTAINER"
        img_lib.ConceptNameCodeSequence = self._generate_code("111028", "DCM", "Image Library")
        img_lib.ContinuityOfContent = "SEPARATE"
        img_lib.ContentSequence = [img_lib_group]

        return img_lib

    def _generate_measurement_group(self, annotation):
        # -------------------------------
        # Item #4 — Measurement Group (one measurement group per annotation)
        # -------------------------------
        measurement_name = ""
        measurement_value = 0
        coords = []
        if annotation.shape == Shape.LINE:
            measurement_name = annotation.measurement_name.capitalize()
            measurement_value = annotation.measurement_value
            coords = annotation.coordinates
        elif annotation.shape == Shape.RECTANGLE:
            measurement_name = annotation.measurement_name.capitalize()
            measurement_value = annotation.measurement_value
            coords = annotation.coordinates
        
        # Tracking Identifier
        tracking_id = Dataset()
        tracking_id.RelationshipType = "HAS OBS CONTEXT"
        tracking_id.ValueType = "TEXT"
        tracking_id.ConceptNameCodeSequence = self._generate_code("112039", "DCM", "Tracking Identifier")
        tracking_id.TextValue = "Cornerstone3DTools@^0.1.0:Length"

        # Tracking UID
        tracking_uid = Dataset()
        tracking_uid.RelationshipType = "HAS OBS CONTEXT"
        tracking_uid.ValueType = "UIDREF"
        tracking_uid.ConceptNameCodeSequence = self._generate_code("112040", "DCM", "Tracking Unique Identifier")
        tracking_uid.UID = generate_uid()
        
        ref_sop = self._generate_referenced_SOP_sequence(
            annotation.sop_class_uid,
            annotation.sop_instance_uid
        )
        if measurement_name == "Length":
            num_item = self._generate_num_item(measurement_name, measurement_value, coords, ref_sop)
        elif measurement_name in ["Perimeter", "Area"]:
            num_item1 = self._generate_num_item("Perimeter", 0, coords, ref_sop)
            num_item2 = self._generate_num_item("Area", measurement_value, coords, ref_sop)

        # Combine into Measurement Group container
        measurement_group = Dataset()
        measurement_group.RelationshipType = "CONTAINS"
        measurement_group.ValueType = "CONTAINER"
        measurement_group.ConceptNameCodeSequence = self._generate_code("125007", "DCM", "Measurement Group")
        measurement_group.ContinuityOfContent = "SEPARATE"

        if measurement_name == "Length":
            measurement_group.ContentSequence = [tracking_id, tracking_uid, num_item]
        elif measurement_name in ["Perimeter", "Area"]:
            measurement_group.ContentSequence = [tracking_id, tracking_uid, num_item1,  num_item2]

        return measurement_group

    def _generate_num_item(self, measurement_name, measurement_value, coords, ref_sop):

        measured_val = self._generate_measured_value_sequence(measurement_name, measurement_value)

        num_item = Dataset()
        num_item.RelationshipType = "CONTAINS"
        num_item.ValueType = "NUM"
        num_item.ConceptNameCodeSequence = self._generate_measurement_concept_name_code_sequence(measurement_name)
        num_item.MeasuredValueSequence = [measured_val]

        image = Dataset()
        image.RelationshipType = "SELECTED FROM"
        image.ValueType = "IMAGE"
        image.ReferencedSOPSequence = [ref_sop]

        coordsTag = Dataset()
        coordsTag.RelationshipType = "INFERRED FROM"
        coordsTag.ValueType = "SCOORD"
        coordsTag.GraphicData = coords
        coordsTag.GraphicType = "POLYLINE"
        coordsTag.ContentSequence = [image]

        # attach SCOORD as sub-item of NUM
        num_item.ContentSequence = [coordsTag]

        return num_item

    def _generate_measured_value_sequence(self, measurement_name, measurement_value):
        """Return a Measured Value Sequence item for NUM."""
        units_map = {
            "Length": ("mm", "UCUM", "millimeter", "1.4"),
            "Perimeter": ("mm", "UCUM", "millimeter", "1.4"),
            "Area": ("mm2", "UCUM", "SquareMilliMeter", "1.4"),
        }

        measured_val = Dataset()
        if measurement_name in units_map:
            uval, uscheme, umean, uver = units_map[measurement_name]
            measured_val.MeasurementUnitsCodeSequence = self._generate_code(uval, uscheme, umean, uver)
            measured_val.NumericValue = measurement_value
        return measured_val

    def _generate_measurement_concept_name_code_sequence(self, measurement_name):
        """Return the coded concept name based on measurement type."""
        mapping = {
            "Length": ("G-D7FE", "SRT", "Length"),
            "Perimeter": ("131191004", "SCT", "Perimeter"),
            "Area": ("G-A166", "SRT", "Area"),
        }
        value, scheme, meaning = mapping.get(measurement_name, ("G-D7FE", "SRT", measurement_name))
        return self._generate_code(value, scheme, meaning)
