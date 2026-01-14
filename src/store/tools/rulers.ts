import { computed } from 'vue';
import { defineAnnotationToolStore } from '@/src/utils/defineAnnotationToolStore';
import type { Vector3 } from '@kitware/vtk.js/types';
import { ToolID } from '@/src/types/annotation-tool';
import { RULER_LABEL_DEFAULTS } from '@/src/config';
import { Manifest, StateFile } from '@/src/io/state-file/schema';
import { getPixelSpacing } from '@/src/utils/dicomMetadata';
import { useAnnotationTool } from './useAnnotationTool';

const rulerDefaults = () => ({
  firstPoint: [0, 0, 0] as Vector3,
  secondPoint: [0, 0, 0] as Vector3,
  id: '',
  name: 'Ruler',
});

export const useRulerStore = defineAnnotationToolStore('ruler', () => {
  const annotationTool = useAnnotationTool({
    toolDefaults: rulerDefaults,
    initialLabels: RULER_LABEL_DEFAULTS,
  });

  // prefix some props with ruler
  const {
    toolIDs: rulerIDs,
    toolByID: rulerByID,
    tools: rulers,
    addTool: addRuler,
    updateTool: updateRuler,
    removeTool: removeRuler,
    jumpToTool: jumpToRuler,
    serializeTools,
    deserializeTools,
  } = annotationTool;

  const lengthByID = computed<Record<string, number>>(() => {
    const byID = rulerByID.value;

    return rulerIDs.value.reduce((lengths, id) => {
      const ruler = byID[id];
      const { firstPoint, secondPoint } = byID[id];

      const spacing: number[] = getPixelSpacing(ruler.imageID)

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

  function getPoints(id: ToolID) {
    const tool = annotationTool.toolByID.value[id];
    return [tool.firstPoint, tool.secondPoint];
  }

  // --- serialization --- //

  function serialize(state: StateFile) {
    state.manifest.tools.rulers = serializeTools();
  }

  function deserialize(manifest: Manifest, dataIDMap: Record<string, string>) {
    deserializeTools(manifest.tools.rulers, dataIDMap);
  }

  return {
    ...annotationTool, // support useAnnotationTool interface (for MeasurementsToolList)
    rulerIDs,
    rulerByID,
    rulers,
    lengthByID,
    addRuler,
    updateRuler,
    removeRuler,
    jumpToRuler,
    getPoints,
    serialize,
    deserialize,
  };
});
