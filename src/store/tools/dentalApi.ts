import { DicomImageMetadata } from '@/src/utils/dicomMetadata';

/* eslint-disable camelcase */
/**
 * Represents a single dental measurement for one side of a tooth.
 * All point coordinates are in pixel space [x, y].
 */
export interface DentalMeasurement {
  side_id: number;
  CEJ: number[]; // Cemento-Enamel Junction
  ALC: number[]; // Alveolar Crest
  APEX: number[]; // Root Apex
  CAL: number; // Clinical Attachment Level (mm)
  TRL: number; // Tooth Root Length (mm)
  ABLD: number; // Alveolar Bone Loss Degree (ratio)
  stage: string; // Periodontal disease stage
}

/**
 * Represents all measurements for a single tooth.
 */
export interface ToothMeasurement {
  teeth_id: number;
  pair_measurements: DentalMeasurement[];
  teeth_center: number[]; // Center position [x, y]
}
/* eslint-enable camelcase */

/**
 * Fetches dental measurements from the API.
 *
 * @param imageID - The image ID
 * @param metadata - DICOM metadata containing patient and study information
 * @returns Promise resolving to array of tooth measurements
 * @throws Error if API request fails
 */
export async function fetchDentalMeasurements(
  imageID: string,
  metadata: DicomImageMetadata
): Promise<ToothMeasurement[]> {
  const { VITE_FOUNDATION_API } = import.meta.env;
  const url = `${VITE_FOUNDATION_API}/get-measurement-dental`;

  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      PatientId: metadata.patientId,
      StudyInstanceUID: metadata.studyInstanceUID,
      SeriesInstanceUID: metadata.seriesInstanceUID,
      SopInstanceUID: metadata.sopInstanceUID,
      ImageID: imageID,
      ScaleX: metadata.pixelSpacing[0],
      ScaleY: metadata.pixelSpacing[1],
    }),
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch dental measurements: ${response.statusText}`);
  }

  return response.json();
}
