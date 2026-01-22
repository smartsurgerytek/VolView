import DicomChunkImage from '@/src/core/streaming/dicomChunkImage';
import { Tags } from '@/src/core/dicomTags';
import { useImageCacheStore } from '@/src/store/image-cache';

/**
 * Extracts pixel spacing from a DICOM image.
 *
 * Pixel spacing represents the physical distance between pixels in mm.
 * Returns [x, y, z] spacing array with default value of [1, 1, 1].
 *
 * @param imageID - The image ID from the image cache
 * @returns Array of [x, y, z] pixel spacing values in mm
 */
export function getPixelSpacing(imageID: string): number[] {
  const imageCacheStore = useImageCacheStore();
  const spacing: number[] = [1, 1, 1];
  const image = imageCacheStore.imageById[imageID];

  if (!(image instanceof DicomChunkImage)) {
    return spacing;
  }

  const metaPairs = image.getDicomMetadata();
  if (!metaPairs) {
    return spacing;
  }

  const metadata = Object.fromEntries(metaPairs);
  const pixelSpacingStr = metadata[Tags.PixelSpacing];

  if (!pixelSpacingStr) {
    return spacing;
  }

  // PixelSpacing format: "row_spacing\column_spacing" (Y\X)
  const pixelSpacing = pixelSpacingStr.split('\\');
  if (pixelSpacing.length >= 2) {
    const rowSpacing = parseFloat(pixelSpacing[0]); // Y
    const colSpacing = parseFloat(pixelSpacing[1]); // X

    if (!Number.isNaN(colSpacing)) {
      spacing[0] = colSpacing;
    }
    if (!Number.isNaN(rowSpacing)) {
      spacing[1] = rowSpacing;
    }
  }

  return spacing;
}

/**
 * Interface for DICOM image identification and measurement data
 */
export interface DicomImageMetadata {
  pixelSpacing: [number, number];
  patientId: string;
  studyInstanceUID: string;
  seriesInstanceUID: string;
  sopInstanceUID: string;
}

/**
 * Extracts comprehensive DICOM metadata from an image.
 *
 * Retrieves patient identification, study/series UIDs, and pixel spacing
 * needed for measurement calculations and API requests.
 *
 * @param imageID - The image ID from the image cache
 * @returns DICOM metadata object with default values if extraction fails
 */
export function getDicomImageMetadata(imageID: string): DicomImageMetadata {
  const imageCacheStore = useImageCacheStore();

  // Default values
  const metadata: DicomImageMetadata = {
    pixelSpacing: [1, 1],
    patientId: '',
    studyInstanceUID: '',
    seriesInstanceUID: '',
    sopInstanceUID: '',
  };

  const image = imageCacheStore.imageById[imageID];
  if (!(image instanceof DicomChunkImage)) {
    return metadata;
  }

  const metaPairs = image.getDicomMetadata();
  if (!metaPairs) {
    return metadata;
  }

  try {
    const dicomTags = Object.fromEntries(metaPairs);

    // Extract UIDs
    metadata.patientId = dicomTags[Tags.PatientID] || '';
    metadata.studyInstanceUID = dicomTags[Tags.StudyInstanceUID] || '';
    metadata.seriesInstanceUID = dicomTags[Tags.SeriesInstanceUID] || '';
    metadata.sopInstanceUID = dicomTags[Tags.SOPInstanceUID] || '';

    // Extract and parse PixelSpacing
    const pixelSpacingStr = dicomTags[Tags.PixelSpacing] as string | undefined;
    if (pixelSpacingStr) {
      const parts = pixelSpacingStr.split('\\');
      if (parts.length >= 2) {
        const rowSpacing = parseFloat(parts[0]); // Y
        const colSpacing = parseFloat(parts[1]); // X

        if (!Number.isNaN(colSpacing)) {
          metadata.pixelSpacing[0] = colSpacing;
        }
        if (!Number.isNaN(rowSpacing)) {
          metadata.pixelSpacing[1] = rowSpacing;
        }
      }
    }
  } catch (error) {
    console.error('Error parsing DICOM metadata:', error);
  }

  return metadata;
}
