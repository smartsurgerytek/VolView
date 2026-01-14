import { computed, ref } from 'vue';
import { defineAnnotationToolStore } from '@/src/utils/defineAnnotationToolStore';
import type { Vector3 } from '@kitware/vtk.js/types';
import { ToolID } from '@/src/types/annotation-tool';
import { DENTAL_LABEL_DEFAULTS } from '@/src/config';
import { Manifest, StateFile } from '@/src/io/state-file/schema';
import { Tags } from '@/src/core/dicomTags';
import DicomChunkImage from '@/src/core/streaming/dicomChunkImage';
import { useCurrentImage } from '@/src/composables/useCurrentImage';
import { useAnnotationTool } from './useAnnotationTool';
import { useImageCacheStore } from '../image-cache';

interface DicomImageData {
  pixelSpacing: [number, number];
  patientId: string;
  studyInstanceUID: string;
  seriesInstanceUID: string;
  sopInstanceUID: string;
}

/* eslint-disable camelcase */
interface DentalMeasurement {
  side_id: number;
  CEJ: number[];
  ALC: number[];
  APEX: number[];
  CAL: number;
  TRL: number;
  ABLD: number;
  stage: string;
}

interface Measurement {
  teeth_id: number;
  pair_measurements: DentalMeasurement[];
  teeth_center: number[];
}
/* eslint-disable camelcase */

interface TRLCALPair {
  trl: {
    firstPoint: Vector3 | number[];
    secondPoint: Vector3 | number[];
  };
  cal: {
    firstPoint: Vector3 | number[];
    secondPoint: Vector3 | number[];
  };
}

interface ToothData {
  centerPosition?: Vector3 | number[];
  trlCalPairs?: TRLCALPair[];
}

interface InferenceData {
  teeth?: Record<string, ToothData>;
}

const dentalDefaults = () => ({
  firstPoint: [0, 0, 0] as Vector3,
  secondPoint: [0, 0, 0] as Vector3,
  id: '',
  name: 'Dental',
  type: 'TRL' as 'TRL' | 'CAL', // Default to TRL  
  toothId: '',
  pairId: '', // For linking TRL/CAL pairs  
});


function getPixelSpacing(currentImageID: string): number[] {
  const imageCacheStore = useImageCacheStore();

  const spacing: number[] = [1, 1, 1];
  const image = imageCacheStore.imageById[currentImageID];

  if (image instanceof DicomChunkImage) {
    const metaPairs = image.getDicomMetadata();
    if (metaPairs) {
      const metadata = Object.fromEntries(metaPairs);
      const pixelSpacingStr = metadata[Tags.PixelSpacing];

      const pixelSpacing = pixelSpacingStr.split('\\');

      if (pixelSpacing.length > 0) {
        spacing[0] = parseFloat(pixelSpacing[0])
        spacing[1] = parseFloat(pixelSpacing[1])
      }
    }
  }

  return spacing;
}

export const useDentalStore = defineAnnotationToolStore('dental', () => {
  const annotationTool = useAnnotationTool({
    toolDefaults: dentalDefaults,
    initialLabels: DENTAL_LABEL_DEFAULTS,
  });

  // prefix some props with dental  
  const {
    toolIDs: dentalIDs,
    toolByID: dentalByID,
    tools: dentalTools,
    addTool: addDental,
    updateTool: updateDentalInternal,
    removeTool: removeDental,
    jumpToTool: jumpToDental,
    serializeTools,
    deserializeTools,
  } = annotationTool;

  // Wrapper for updateTool that synchronizes paired TRL/CAL measurements
  const updateDental = (id: ToolID, patch: any) => {
    const tool = dentalByID.value[id];

    // Check if firstPoint (CEJ) is being updated
    if (patch.firstPoint && tool?.pairId && tool?.toothId) {
      // Find the paired measurement (TRL if this is CAL, or CAL if this is TRL)
      const pairedTool = dentalTools.value.find(
        t => t.pairId === tool.pairId &&
          t.toothId === tool.toothId &&
          t.id !== id
      );

      if (pairedTool) {
        // Update the paired measurement's firstPoint (CEJ) as well
        updateDentalInternal(pairedTool.id, {
          firstPoint: patch.firstPoint,
        });
      }
    }

    // Update the current tool
    updateDentalInternal(id, patch);
  };

  const lengthByID = computed<Record<string, number>>(() => {
    const byID = dentalByID.value;
    return dentalIDs.value.reduce((lengths, id) => {
      const dental = byID[id];
      const { firstPoint, secondPoint } = byID[id];

      const spacing: number[] = getPixelSpacing(dental.imageID)

      // turn index space distance to world space
      const dx = (firstPoint[0] - secondPoint[0]) * spacing[0];
      const dy = (firstPoint[1] - secondPoint[1]) * spacing[1];
      const dz = (firstPoint[2] - secondPoint[2]) * spacing[2];
      const distance = Math.sqrt(dx * dx + dy * dy + dz * dz);

      return Object.assign(lengths, {
        [id]: distance,
      });
    }, {});
  });

  // Calculate ABLD for TRL/CAL pairs  
  const calculateABLD = (trlId: ToolID, calId: ToolID): number | null => {
    const trlLength = lengthByID.value[trlId];
    const calLength = lengthByID.value[calId];

    if (!trlLength || trlLength === 0) return null;
    return calLength / trlLength;
  };

  // Get TRL/CAL pairs for a tooth  
  const getToothPairs = (toothId: string) => {
    const tools = dentalTools.value.filter(tool => tool.toothId === toothId);
    const trlLines = tools.filter(tool => tool.type === 'TRL');
    const calLines = tools.filter(tool => tool.type === 'CAL');

    return trlLines.map(trl => {
      const cal = calLines.find(c => c.pairId === trl.pairId);
      return {
        trl,
        cal,
        abld: cal ? calculateABLD(trl.id, cal.id) : null,
      };
    }).filter(pair => pair.cal);
  };

  function getPoints(id: ToolID) {
    const tool = annotationTool.toolByID.value[id];
    return [tool.firstPoint, tool.secondPoint];
  }

  function getDicomImageData(currentImageID: string): DicomImageData {
    const imageCacheStore = useImageCacheStore();

    // default value
    const data = {
      pixelSpacing: [1, 1] as [number, number],
      patientId: "",
      studyInstanceUID: "",
      seriesInstanceUID: "",
      sopInstanceUID: "",
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

      // --- 1. get UIDs ---
      data.patientId = metadata[Tags.PatientID] || "";
      data.studyInstanceUID = metadata[Tags.StudyInstanceUID] || "";
      data.seriesInstanceUID = metadata[Tags.SeriesInstanceUID] || "";
      data.sopInstanceUID = metadata[Tags.SOPInstanceUID] || "";

      // --- 2. get PixelSpacing ---
      const pixelSpacingStr = metadata[Tags.PixelSpacing] as string | undefined;

      if (pixelSpacingStr) {
        const parts = pixelSpacingStr.split('\\');
        if (parts.length >= 2) {
          const colSpacing = parseFloat(parts[1]); // X 
          const rowSpacing = parseFloat(parts[0]); // Y 

          if (!Number.isNaN(colSpacing)) {
            data.pixelSpacing[0] = colSpacing; // X
          }
          if (!Number.isNaN(rowSpacing)) {
            data.pixelSpacing[1] = rowSpacing; // Y
          }
        }
      }

    } catch (error) {
      console.error("Error parsing DICOM metadata:", error);
    }

    return data;
  }

  async function fetchApiRulers(currentImageID: string, dicomData: DicomImageData): Promise<Measurement[]> {
    const {
      patientId,
      pixelSpacing,
      studyInstanceUID,
      seriesInstanceUID,
      sopInstanceUID,
    } = dicomData;

    const { VITE_FOUNDATION_API } = import.meta.env;
    const url = `${VITE_FOUNDATION_API}/get-measurement-dental`

    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        PatientId: patientId,
        StudyInstanceUID: studyInstanceUID,
        SeriesInstanceUID: seriesInstanceUID,
        SopInstanceUID: sopInstanceUID,
        ImageID: currentImageID,
        ScaleX: pixelSpacing[0],
        ScaleY: pixelSpacing[1],
      }),
    });

    if (!response.ok) {
      throw new Error(`Server error: ${response.statusText}`);
    }

    const responseData = await response.json() as Measurement[];
    return responseData;
  }

  const inferenceData = ref<InferenceData>({});

  const setInferenceData = (data: InferenceData, imageID?: string) => {
    console.log('Setting dental inference data:', data);

    inferenceData.value = data;

    // Process inference data and create dental lines
    if (data.teeth && imageID) {
      // Get the TRL and CAL label IDs
      const trlLabelEntry = annotationTool.findLabel('TRL');
      const calLabelEntry = annotationTool.findLabel('CAL');
      const trlLabelId = trlLabelEntry ? trlLabelEntry[0] : '';
      const calLabelId = calLabelEntry ? calLabelEntry[0] : '';

      Object.entries(data.teeth).forEach(([toothId, toothData]: [string, any]) => {
        if (toothData.centerPosition) {
          // Add tooth center position if needed
        }
        if (toothData.trlCalPairs) {
          toothData.trlCalPairs.forEach((pair: any, index: number) => {
            const pairId = `${toothId}_${index}`;

            // Create a simple frame of reference (assuming axial/superior view at slice 0)
            const frameOfReference = {
              planeOrigin: [0, 0, 0],
              planeNormal: [0, 0, 1], // Superior direction (axial view)
            };

            // Add TRL line
            if (pair.trl) {
              addDental({
                ...pair.trl,
                type: 'TRL',
                toothId,
                pairId,
                imageID,
                frameOfReference,
                slice: 0, // Assume slice 0 for test data
                label: trlLabelId,
                placing: false, // Mark as finished, not being placed
                ...(trlLabelId && annotationTool.labels.value[trlLabelId]),
              });
            }

            // Add CAL line
            if (pair.cal) {
              addDental({
                ...pair.cal,
                type: 'CAL',
                toothId,
                pairId,
                imageID,
                frameOfReference,
                slice: 0, // Assume slice 0 for test data
                label: calLabelId,
                placing: false, // Mark as finished, not being placed
                ...(calLabelId && annotationTool.labels.value[calLabelId]),
              });
            }
          });
        }
      });
    }
  };

  // --- API integration for inference results --- //
  const loadInferenceData = async () => {
    try {
      const currentImageID = useCurrentImage()?.currentImageID?.value;
      if (!currentImageID)
        return

      const dicomData = getDicomImageData(currentImageID);

      const measurements = await fetchApiRulers(currentImageID, dicomData);
      console.log('Fetched dental measurements from API:', measurements);

      // Process measurements into inference data format
      const data: InferenceData = { teeth: {} };

      // TRL = CEJ to APEX
      // CAL = CEJ to ALC
      // Set index-Z to 0 for 2D representation
      measurements.forEach((measurement) => {
        const toothId = `tooth_${measurement.teeth_id}`;
        data.teeth![toothId] = {
          centerPosition: [...measurement.teeth_center, 0],
          trlCalPairs: measurement.pair_measurements.map((pair) => ({
            trl: {
              firstPoint: [...pair.CEJ, 0],
              secondPoint: [...pair.APEX, 0],
            },
            cal: {
              firstPoint: [...pair.CEJ, 0],
              secondPoint: [...pair.ALC, 0],
            }
          }))
        };
      });

      setInferenceData(data, currentImageID);
    } catch (error) {
      console.error('Failed to fetch inference results:', error);
    }
  };

  // --- serialization --- //

  function serialize(state: StateFile) {
    state.manifest.tools.dental = serializeTools();
  }

  function deserialize(manifest: Manifest, dataIDMap: Record<string, string>) {
    deserializeTools(manifest.tools.dental, dataIDMap);
  }

  return {
    ...annotationTool, // support useAnnotationTool interface
    updateTool: updateDental, // Override updateTool to use our wrapper
    toolIDs: dentalIDs,
    toolByID: dentalByID,
    tools: dentalTools,
    loadInferenceData,

    dentalIDs,
    dentalByID,
    dentalTools,
    lengthByID,
    addDental,
    updateDental,
    removeDental,
    jumpToDental,
    getPoints,
    calculateABLD,
    getToothPairs,
    setInferenceData,
    inferenceData,
    serialize,
    deserialize,
  };
});