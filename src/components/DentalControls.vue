<script setup lang="ts">
import { computed } from 'vue';
import { storeToRefs } from 'pinia';
import { useToolStore } from '@/src/store/tools';
import { Tools } from '@/src/store/tools/types';
import { useDentalStore } from '@/src/store/tools/dental';

const toolStore = useToolStore();
const dentalStore = useDentalStore();

const { activeLabel, labels } = storeToRefs(dentalStore);

const isDentalToolActive = computed(() => toolStore.currentTool === Tools.Dental);

// Get the label ID for TRL and CAL by searching for the label name
const getTRLLabelId = () => {
  const entry = dentalStore.findLabel('TRL');
  return entry ? entry[0] : '';
};

const getCALLabelId = () => {
  const entry = dentalStore.findLabel('CAL');
  return entry ? entry[0] : '';
};

// Check which type is currently active by label name
const activeLabelName = computed(() => {
  if (!activeLabel.value) return '';
  return labels.value[activeLabel.value]?.labelName || '';
});

function activateTRLTool() {
  toolStore.setCurrentTool(Tools.Dental);
  const trlLabelId = getTRLLabelId();
  if (trlLabelId) dentalStore.setActiveLabel(trlLabelId);
}

function activateCALTool() {
  toolStore.setCurrentTool(Tools.Dental);
  const calLabelId = getCALLabelId();
  if (calLabelId) dentalStore.setActiveLabel(calLabelId);
}  
</script>  
  
<template>
  <div class="pa-3">
    <div class="header mb-3">Dental Tools</div>

    <div class="content">
      <v-row dense>
        <v-col cols="6">
          <v-btn
            :color="activeLabelName === 'TRL' && isDentalToolActive ? 'primary' : 'default'"
            :variant="activeLabelName === 'TRL' && isDentalToolActive ? 'flat' : 'outlined'"
            @click="activateTRLTool"
            class="w-100"
            prepend-icon="mdi-ruler"
          >
            TRL
          </v-btn>
        </v-col>

        <v-col cols="6">
          <v-btn
            :color="activeLabelName === 'CAL' && isDentalToolActive ? 'primary' : 'default'"
            :variant="activeLabelName === 'CAL' && isDentalToolActive ? 'flat' : 'outlined'"
            @click="activateCALTool"
            class="w-100"
            prepend-icon="mdi-ruler"
          >
            CAL
          </v-btn>
        </v-col>
      </v-row>
    </div>

    <v-divider class="my-3" />

    <div class="info-section">
      <h4 class="text-subtitle-2 mb-2">Instructions</h4>
      <ul class="text-caption">
        <li>Click TRL or CAL to activate the tool</li>
        <li>Click two points to draw each line</li>
        <li>Lines are automatically completed</li>
        <li>Switch tools or continue drawing more lines</li>
        <li>ABLD = CAL length / TRL length</li>
      </ul>
    </div>
  </div>
</template>  
  
<style scoped>  
.header {  
  font-weight: 600;  
  font-size: 1.1rem;  
}  
  
.content {  
  display: flex;  
  flex-direction: column;  
  gap: 8px;  
}  
  
.info-section ul {  
  padding-left: 16px;  
  margin: 0;  
}  
  
.info-section li {  
  margin-bottom: 4px;  
}  
</style>