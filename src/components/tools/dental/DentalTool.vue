<template>
  <div class="overlay-no-events">
    <svg class="overlay-no-events">
      <dental-widget-2D v-for="line in dentalLines" :key="line.id" :tool-id="line.id"
        :is-placing="line.id === placingLineID" :image-id="imageId" :view-id="viewId" :view-direction="viewDirection"
        :line-type="line.type" @contextmenu="openContextMenu(line.id, $event)" @placed="onLinePlaced"
        @widgetHover="onHover(line.id, $event)" />
    </svg>
    <annotation-info :info="overlayInfo" :tool-store="dentalStore" />
    <annotation-context-menu ref="contextMenu" :tool-store="dentalStore" />
  </div>
</template>

<script lang="ts">
import { computed, defineComponent, onUnmounted, PropType, toRefs } from 'vue';
import { useImage } from '@/src/composables/useCurrentImage';
import { useToolStore } from '@/src/store/tools';
import { Tools } from '@/src/store/tools/types';
import { useDentalStore } from '@/src/store/tools/dental';
import { getLPSAxisFromDir } from '@/src/utils/lps';
import DentalWidget2D from '@/src/components/tools/dental/DentalWidget2D.vue';
import { LPSAxisDir } from '@/src/types/lps';
import { storeToRefs } from 'pinia';
import {
  useContextMenu,
  useCurrentTools,
  useHover,
  usePlacingAnnotationTool,
} from '@/src/composables/annotationTool';
import AnnotationContextMenu from '@/src/components/tools/AnnotationContextMenu.vue';
import AnnotationInfo from '@/src/components/tools/AnnotationInfo.vue';
import { useFrameOfReference } from '@/src/composables/useFrameOfReference';
import { Maybe } from '@/src/types';
import { useSliceInfo } from '@/src/composables/useSliceInfo';
import { watchImmediate } from '@vueuse/core';

export default defineComponent({
  name: 'DentalTool',
  props: {
    viewId: {
      type: String,
      required: true,
    },
    viewDirection: {
      type: String as PropType<LPSAxisDir>,
      required: true,
    },
    imageId: String as PropType<Maybe<string>>,
  },
  components: {
    DentalWidget2D,
    AnnotationContextMenu,
    AnnotationInfo,
  },
  setup(props) {
    const { viewDirection, imageId, viewId } = toRefs(props);
    const toolStore = useToolStore();
    const dentalStore = useDentalStore();
    const { activeLabel, labels } = storeToRefs(dentalStore);

    const sliceInfo = useSliceInfo(viewId, imageId);
    const slice = computed(() => sliceInfo.value?.slice ?? 0);

    const { metadata: imageMetadata } = useImage(imageId);
    const isToolActive = computed(() => toolStore.currentTool === Tools.Dental);
    const viewAxis = computed(() => getLPSAxisFromDir(viewDirection.value));

    // --- active dental line management --- //  

    const frameOfReference = useFrameOfReference(
      viewDirection,
      slice,
      imageMetadata
    );

    const placingTool = usePlacingAnnotationTool(
      dentalStore,
      computed(() => {
        if (!imageId.value) return {};
        // Get the label name from the active label ID
        const labelName = activeLabel.value ? labels.value[activeLabel.value]?.labelName : '';
        return {
          imageID: imageId.value,
          frameOfReference: frameOfReference.value,
          slice: slice.value,
          label: activeLabel.value,
          type: labelName as 'TRL' | 'CAL', // Set type to match the label name (TRL or CAL)
          ...(activeLabel.value && labels.value[activeLabel.value]),
        };
      })
    );

    watchImmediate([isToolActive, imageId] as const, ([active, imageID]) => {
      placingTool.remove();
      if (active && imageID) {
        placingTool.add();
      }
    });


    onUnmounted(() => {
      placingTool.remove();
    });

    const onLinePlaced = () => {
      if (imageId.value) {
        placingTool.commit();
        placingTool.add();
      }
    };

    // --- //  

    const { contextMenu, openContextMenu } = useContextMenu();

    // --- dental line data --- //  

    const currentTools = useCurrentTools(dentalStore, viewAxis);

    const currentDentalLines = computed(() => {
      const { lengthByID } = dentalStore;
      const tools = currentTools.value.map((line) => ({
        ...line,
        length: lengthByID[line.id],
        type: line.type || 'TRL',
      }));
      return tools;
    });


    const { onHover, overlayInfo } = useHover(currentTools, slice);

    return {
      dentalLines: currentDentalLines,
      placingLineID: placingTool.id,
      onLinePlaced,
      contextMenu,
      openContextMenu,
      dentalStore,
      onHover,
      overlayInfo,
    };
  },
});  
</script>

<style scoped src="@/src/components/styles/vtk-view.css"></style>