import { useCurrentImage } from '@/src/composables/useCurrentImage';
import vtkImageData from '@kitware/vtk.js/Common/DataModel/ImageData';
import vtkLabelMap from '@/src/vtk/LabelMap';
import DicomChunkImage from '@/src/core/streaming/dicomChunkImage';
import { Tags } from '@/src/core/dicomTags';
import { readImage } from '@/src/io/readWriteImage';
import { useImageCacheStore } from '../image-cache';
import {
  SegmentGroupMetadata,
  toLabelMap,
  useSegmentGroupStore,
} from '../segmentGroups';

const { VITE_FASTAPI_URL } = import.meta.env;
const { VITE_FOUNDATION_API } = import.meta.env;

const DENTAL_CLASS_MAP: Record<
  number,
  { name: string; color: [number, number, number, number] }
> = {
  1: { name: 'Crown', color: [227, 26, 28, 255] }, // API ID 0
  2: { name: 'Alveolar_bone', color: [31, 120, 180, 255] }, // API ID 1
  3: { name: 'Caries', color: [178, 223, 138, 255] }, // API ID 2
  4: { name: 'Dentin', color: [51, 160, 44, 255] }, // API ID 3
  5: { name: 'Pulp', color: [251, 154, 153, 255] }, // API ID 4
  6: { name: 'Maxillary_sinus', color: [253, 191, 111, 255] }, // API ID 5
  7: { name: 'Implant', color: [255, 127, 0, 255] }, // API ID 6
  8: { name: 'Enamel', color: [202, 178, 214, 255] }, // API ID 7
  9: { name: 'Post_and_core', color: [106, 61, 154, 255] }, // API ID 8
  10: { name: 'Restoration', color: [255, 255, 153, 255] }, // API ID 9
  11: { name: 'Periapical_lesion', color: [177, 89, 40, 255] }, // API ID 10
  12: { name: 'Root_canal_filling', color: [166, 206, 227, 255] }, // API ID 11
  13: { name: 'Mandibular_alveolar_nerve', color: [179, 226, 205, 255] }, // API ID 12
};

interface DicomImageData {
  studyInstanceUID: string;
  seriesInstanceUID: string;
  sopInstanceUID: string;
}

function generateSegmentMetadata(parentImageID: string): SegmentGroupMetadata {
  const order: number[] = [];
  const byValue: Record<number, any> = {};

  for (const key in DENTAL_CLASS_MAP) {
    const value = Number(key);
    order.push(value);
    byValue[value] = {
      value: value,
      name: DENTAL_CLASS_MAP[value].name,
      color: DENTAL_CLASS_MAP[value].color,
      visible: true,
    };
  }

  return {
    name: 'Dental Segmentation',
    parentImage: parentImageID,
    segments: {
      order: order,
      byValue: byValue,
    },
  };
}

async function fetchApiRulers(dicomData: DicomImageData) {
  const { studyInstanceUID, seriesInstanceUID, sopInstanceUID } = dicomData;

  // only axial view is supported in current API, so we capture the canvas as base64 image to send to API for segmentation
  const canvas = document.querySelector('canvas');
  const base64 = canvas?.toDataURL('image/png');

  const response = await fetch(`${VITE_FOUNDATION_API}/get_segmentation`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      StudyInstanceUID: studyInstanceUID,
      SeriesInstanceUID: seriesInstanceUID,
      SopInstanceUID: sopInstanceUID,
      Base64ImageString: base64
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    console.error('API Error Response:', errorText);
    throw new Error(`API Error: ${response.status} ${response.statusText}`);
  }

  const segmentationBlob = await response.blob();
  return segmentationBlob;
}

function getDicomImageData(currentImageID: string): DicomImageData {
  const imageCacheStore = useImageCacheStore();

  // default value
  const data = {
    studyInstanceUID: '',
    seriesInstanceUID: '',
    sopInstanceUID: '',
  };

  const image = imageCacheStore.imageById[currentImageID];

  if (!(image instanceof DicomChunkImage)) {
    return data;
  }

  const metaPairs = image.getDicomMetadata();
  if (!metaPairs) {
    return data;
  }

  try {
    const metadata = Object.fromEntries(metaPairs);

    data.studyInstanceUID = metadata[Tags.StudyInstanceUID] || '';
    data.seriesInstanceUID = metadata[Tags.SeriesInstanceUID] || '';
    data.sopInstanceUID = metadata[Tags.SOPInstanceUID] || '';
  } catch (error) {
    console.error('Error parsing DICOM metadata:', error);
  }

  return data;
}

export async function getSegmentation() {
  const segmentGroupStore = useSegmentGroupStore();

  try {
    // get currentImageID
    const currentImageID = useCurrentImage()?.currentImageID?.value;
    if (!currentImageID) return;

    // get dicom data
    const dicomData = getDicomImageData(currentImageID);
    if (!dicomData || !dicomData.sopInstanceUID) {
      console.error('無法取得 DICOM 資料或 SopInstanceUID');
      return;
    }

    // get vti File
    const segmentationBlob: Blob = await fetchApiRulers(dicomData);
    const vtiFileName = `segmentation_${dicomData.sopInstanceUID}.vti`;
    const vtiFile = new File([segmentationBlob], vtiFileName, {
      type: 'application/xml',
    });

    // input vti File
    const vtkImage: vtkImageData = await readImage(vtiFile);
    const labelmapImage: vtkLabelMap = toLabelMap(vtkImage);

    // generate lebel
    const metadata: SegmentGroupMetadata =
      generateSegmentMetadata(currentImageID);
    const segmentGroupID = segmentGroupStore.addLabelmap(
      labelmapImage,
      metadata
    );

    console.log('Segmentation added with Group ID:', segmentGroupID);

    console.log('getSegmentation');
  } catch (error) {
    console.error('Failed to get or process segmentation:', error);
  }
}
