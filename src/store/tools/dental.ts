import { computed, ref } from 'vue';
import { defineAnnotationToolStore } from '@/src/utils/defineAnnotationToolStore';
import type { Vector3 } from '@kitware/vtk.js/types';
import { ToolID } from '@/src/types/annotation-tool';
import { DENTAL_LABEL_DEFAULTS } from '@/src/config';
import { Manifest, StateFile } from '@/src/io/state-file/schema';
import { useCurrentImage } from '@/src/composables/useCurrentImage';
import { useToast } from '@/src/composables/useToast';
import { getPixelSpacing, getDicomImageMetadata } from '@/src/utils/dicomMetadata';
import type { InferenceData } from '@/src/types/dental';
import { useAnnotationTool } from './useAnnotationTool';
import {
  fetchDentalMeasurements,
  type ToothMeasurement,
} from './dentalApi';

// --- Tool Defaults --- //

const dentalDefaults = () => ({
  firstPoint: [0, 0, 0] as Vector3,
  secondPoint: [0, 0, 0] as Vector3,
  id: '',
  name: 'Dental',
  type: 'TRL' as 'TRL' | 'CAL',
  toothId: '',
  pairId: '', // Links TRL/CAL pairs together
});

// --- Store Definition --- //

export const useDentalStore = defineAnnotationToolStore('dental', () => {
  const annotationTool = useAnnotationTool({
    toolDefaults: dentalDefaults,
    initialLabels: DENTAL_LABEL_DEFAULTS,
  });

  // Destructure with dental-specific naming
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

  // --- State --- //

  const inferenceData = ref<InferenceData>({});
  const isLoadingInference = ref(false);
  const hasLoadedInference = ref(false);

  // Track which images have loaded inference data
  const loadedImageIDs = ref<Set<string>>(new Set());

  // --- Computed Properties --- //

  /**
   * Computes the physical length for each dental measurement.
   * Converts index space distances to world space using pixel spacing.
   */
  const lengthByID = computed<Record<string, number>>(() => {
    const byID = dentalByID.value;
    return dentalIDs.value.reduce((lengths, id) => {
      const dental = byID[id];
      const { firstPoint, secondPoint } = dental;
      const spacing = getPixelSpacing(dental.imageID);

      // Convert index space distance to world space (mm)
      const dx = (firstPoint[0] - secondPoint[0]) * spacing[0];
      const dy = (firstPoint[1] - secondPoint[1]) * spacing[1];
      const dz = (firstPoint[2] - secondPoint[2]) * spacing[2];
      const distance = Math.sqrt(dx * dx + dy * dy + dz * dz);

      return Object.assign(lengths, { [id]: distance });
    }, {});
  });

  // --- Methods --- //

  /**
   * Updates a dental measurement, ensuring paired TRL/CAL measurements
   * stay synchronized at their shared CEJ (Cemento-Enamel Junction) point.
   *
   * When the firstPoint (CEJ) is updated on either TRL or CAL, the paired
   * measurement is automatically updated to maintain consistency.
   *
   * @param id - The tool ID to update
   * @param patch - Partial updates to apply
   */
  const updateDental = (id: ToolID, patch: any) => {
    const tool = dentalByID.value[id];

    // Synchronize CEJ point across paired measurements
    if (patch.firstPoint && tool?.pairId && tool?.toothId) {
      const pairedTool = dentalTools.value.find(
        (t) =>
          t.pairId === tool.pairId &&
          t.toothId === tool.toothId &&
          t.id !== id
      );

      if (pairedTool) {
        updateDentalInternal(pairedTool.id, {
          firstPoint: patch.firstPoint,
        });
      }
    }

    updateDentalInternal(id, patch);
  };

  /**
   * Calculates the Alveolar Bone Loss Degree (ABLD) ratio.
   * ABLD = CAL length / TRL length
   *
   * @param trlId - The TRL measurement ID
   * @param calId - The CAL measurement ID
   * @returns ABLD ratio or null if TRL is zero/missing
   */
  const calculateABLD = (trlId: ToolID, calId: ToolID): number | null => {
    const trlLength = lengthByID.value[trlId];
    const calLength = lengthByID.value[calId];

    if (!trlLength || trlLength === 0) return null;
    return calLength / trlLength;
  };

  /**
   * Gets all TRL/CAL measurement pairs for a specific tooth.
   *
   * @param toothId - The tooth identifier
   * @returns Array of paired measurements with computed ABLD values
   */
  const getToothPairs = (toothId: string) => {
    const tools = dentalTools.value.filter((tool) => tool.toothId === toothId);
    const trlLines = tools.filter((tool) => tool.type === 'TRL');
    const calLines = tools.filter((tool) => tool.type === 'CAL');

    return trlLines
      .map((trl) => {
        const cal = calLines.find((c) => c.pairId === trl.pairId);
        return {
          trl,
          cal,
          abld: cal ? calculateABLD(trl.id, cal.id) : null,
        };
      })
      .filter((pair) => pair.cal);
  };

  /**
   * Gets the first and second points for a dental measurement.
   *
   * @param id - The tool ID
   * @returns Array containing [firstPoint, secondPoint]
   */
  function getPoints(id: ToolID) {
    const tool = annotationTool.toolByID.value[id];
    return [tool.firstPoint, tool.secondPoint];
  }

  /**
   * Clears dental measurements and inference data for a specific image.
   * If no imageID is provided, clears all data.
   *
   * @param imageID - Optional image ID to clear data for
   */
  const clearInferenceData = (imageID?: string) => {
    console.log('Clearing dental inference data', imageID ? `for image: ${imageID}` : 'for all images');

    if (imageID) {
      // Remove only dental tools for the specified image
      const toolsToRemove = dentalTools.value
        .filter((tool) => tool.imageID === imageID)
        .map((tool) => tool.id);

      toolsToRemove.forEach((id) => {
        removeDental(id);
      });

      // Remove from loaded images set
      loadedImageIDs.value.delete(imageID);
    } else {
      // Remove all existing dental tools
      const toolsToRemove = [...dentalIDs.value];
      toolsToRemove.forEach((id) => {
        removeDental(id);
      });

      // Clear all loaded images
      loadedImageIDs.value.clear();
    }

    // Clear inference data
    inferenceData.value = {};
  };

  /**
   * Sets inference data and creates corresponding dental measurement tools.
   *
   * @param data - Inference data containing tooth measurements
   * @param imageID - Optional image ID to associate measurements with
   */
  const setInferenceData = (data: InferenceData, imageID?: string) => {
    console.log('Setting dental inference data:', data);

    inferenceData.value = data;

    // Create dental lines from inference data
    if (data.teeth && imageID) {
      const trlLabelEntry = annotationTool.findLabel('TRL');
      const calLabelEntry = annotationTool.findLabel('CAL');
      const trlLabelId = trlLabelEntry ? trlLabelEntry[0] : '';
      const calLabelId = calLabelEntry ? calLabelEntry[0] : '';

      // Get colors from DENTAL_LABEL_DEFAULTS as fallback
      const trlDefaults = DENTAL_LABEL_DEFAULTS.TRL;
      const calDefaults = DENTAL_LABEL_DEFAULTS.CAL;

      Object.entries(data.teeth).forEach(([toothId, toothData]) => {
        if (toothData.trlCalPairs) {
          toothData.trlCalPairs.forEach((pair, index) => {
            const pairId = `${toothId}_${index}`;

            // Frame of reference (assuming axial/superior view at slice 0)
            const frameOfReference = {
              planeOrigin: [0, 0, 0] as Vector3,
              planeNormal: [0, 0, 1] as Vector3,
            };

            // Add TRL line
            if (pair.trl) {
              addDental({
                firstPoint: pair.trl.firstPoint as Vector3,
                secondPoint: pair.trl.secondPoint as Vector3,
                type: 'TRL',
                toothId,
                pairId,
                imageID,
                frameOfReference,
                slice: 0,
                label: trlLabelId,
                placing: false,
                // Use label props if available, otherwise use defaults
                ...(trlLabelId
                  ? annotationTool.labels.value[trlLabelId]
                  : trlDefaults),
              });
            }

            // Add CAL line
            if (pair.cal) {
              addDental({
                firstPoint: pair.cal.firstPoint as Vector3,
                secondPoint: pair.cal.secondPoint as Vector3,
                type: 'CAL',
                toothId,
                pairId,
                imageID,
                frameOfReference,
                slice: 0,
                label: calLabelId,
                placing: false,
                // Use label props if available, otherwise use defaults
                ...(calLabelId
                  ? annotationTool.labels.value[calLabelId]
                  : calDefaults),
              });
            }
          });
        }
      });
    }
  };

  /**
   * Transforms API measurement data into the internal inference data format.
   *
   * @param measurements - Raw measurements from the API
   * @returns Formatted inference data
   */
  const transformMeasurementsToInferenceData = (
    measurements: ToothMeasurement[]
  ): InferenceData => {
    const data: InferenceData = { teeth: {} };

    // TRL = CEJ to APEX (Tooth Root Length)
    // CAL = CEJ to ALC (Clinical Attachment Level)
    // Set Z-index to 0 for 2D representation
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
          },
        })),
      };
    });

    return data;
  };

  /**
   * Loads dental inference data from the API for the current image.
   *
   * Fetches measurements, transforms them to the internal format,
   * and creates dental measurement tools. Automatically replaces
   * existing measurements for the image.
   */
  const loadInferenceData = async () => {
    try {
      isLoadingInference.value = true;
      const toast = useToast();
      const currentImageID = useCurrentImage()?.currentImageID?.value;

      if (!currentImageID) {
        return;
      }

      const metadata = getDicomImageMetadata(currentImageID);
      const measurements = await fetchDentalMeasurements(
        currentImageID,
        metadata
      );

      console.log('Fetched dental measurements from API:', measurements);

      const data = transformMeasurementsToInferenceData(measurements);

      // Clear existing data for this image before loading new data
      // This ensures we replace old measurements with fresh API data
      clearInferenceData(currentImageID);
      toast.success('Dental inference data loaded!');
      setInferenceData(data, currentImageID);
      hasLoadedInference.value = true;

      // Mark this image as having loaded data
      loadedImageIDs.value.add(currentImageID);
    } catch (error) {
      console.error('Failed to fetch inference results:', error);
    } finally {
      isLoadingInference.value = false;
    }
  };

  // --- Serialization --- //

  function serialize(state: StateFile) {
    state.manifest.tools.dental = serializeTools();
  }

  function deserialize(manifest: Manifest, dataIDMap: Record<string, string>) {
    deserializeTools(manifest.tools.dental, dataIDMap);

    // Enable the dental module if there are dental tools in the manifest
    if (manifest.tools.dental?.tools?.length) {
      hasLoadedInference.value = true;

      // Rebuild inferenceData from deserialized tools
      const rebuiltData: InferenceData = { teeth: {} };

      manifest.tools.dental.tools.forEach((tool) => {
        const mappedImageID = dataIDMap[tool.imageID] || tool.imageID;
        loadedImageIDs.value.add(mappedImageID);

        const { toothId, pairId, type, firstPoint, secondPoint } = tool;

        // Initialize tooth data if not exists
        if (!rebuiltData.teeth![toothId]) {
          rebuiltData.teeth![toothId] = {
            centerPosition: undefined,
            trlCalPairs: [],
          };
        }

        // Extract pair index from pairId (format: "toothId_index")
        const pairIndex = parseInt(pairId.split('_').pop() || '0', 10);

        // Ensure the pair array is long enough
        const toothData = rebuiltData.teeth![toothId];
        while (toothData.trlCalPairs!.length <= pairIndex) {
          toothData.trlCalPairs!.push({
            trl: { firstPoint: [0, 0, 0], secondPoint: [0, 0, 0] },
            cal: { firstPoint: [0, 0, 0], secondPoint: [0, 0, 0] },
          });
        }

        // Set TRL or CAL data based on type
        const pair = toothData.trlCalPairs![pairIndex];
        if (type === 'TRL') {
          pair.trl = { firstPoint, secondPoint };
        } else if (type === 'CAL') {
          pair.cal = { firstPoint, secondPoint };
        }
      });

      inferenceData.value = rebuiltData;
    }
  }

  // --- Return Store Interface --- //

  return {
    ...annotationTool, // Support useAnnotationTool interface
    updateTool: updateDental, // Override with synchronized version
    toolIDs: dentalIDs,
    toolByID: dentalByID,
    tools: dentalTools,
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
    clearInferenceData,
    inferenceData,
    loadInferenceData,
    isLoadingInference,
    hasLoadedInference,
    loadedImageIDs,
    serialize,
    deserialize,
  };
});
