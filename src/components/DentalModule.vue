<script setup lang="ts">
import { ref, computed } from 'vue';
import { storeToRefs } from 'pinia';
import { useDentalStore } from '@/src/store/tools/dental';
import { useCurrentImage } from '@/src/composables/useCurrentImage';
import DentalControls from './DentalControls.vue';
import DentalMeasurementsList from './DentalMeasurementsList.vue';

const tab = ref('controls');
const dentalStore = useDentalStore();
const { currentImageID } = useCurrentImage();
const { inferenceData } = storeToRefs(dentalStore);

const getPeriodontalStage = (abld: number): { stage: number; color: string } => {
  if (abld === 0) {
    return { stage: 0, color: 'success' };
  }
  if (abld < 0.15) {
    return { stage: 1, color: 'info' };
  }
  if (abld < 0.33) {
    return { stage: 2, color: 'warning' };
  }
  return { stage: 3, color: 'error' };
};

const teethList = computed(() => {
  if (!inferenceData.value?.teeth) return [];

  return Object.entries(inferenceData.value.teeth).map(([toothId, toothData]: [string, any]) => {
    const pairs = dentalStore.getToothPairs(toothId);
    return {
      toothId,
      centerPosition: toothData.centerPosition,
      pairs,
    };
  });
});  
</script>

<template>
  <div class="overflow-y-auto mx-2 fill-height">
    <dental-controls />
    <v-divider thickness="4" />

    <v-tabs v-model="tab" align-tabs="center" density="compact" class="my-1">
      <v-tab value="controls" class="tab-header">Controls</v-tab>
      <v-tab value="teeth" class="tab-header">Teeth</v-tab>
      <v-tab value="measurements" class="tab-header">Measurements</v-tab>
    </v-tabs>

    <v-window v-model="tab">
      <v-window-item value="controls">
        <div class="pa-3">
          <h3 class="text-h6 mb-3">Dental Analysis</h3>
          <v-btn v-if="currentImageID" @click="() => dentalStore.loadInferenceData()" color="primary" class="mb-3">
            Refresh Inference Results
          </v-btn>

          <div v-if="inferenceData?.teeth" class="text-body-2">
            <p>Found {{ Object.keys(inferenceData.teeth).length }} teeth with analysis data</p>
          </div>
        </div>
      </v-window-item>

      <v-window-item value="teeth">
        <div class="pa-3">
          <h3 class="text-h6 mb-3">Teeth Analysis</h3>
          <v-expansion-panels>
            <v-expansion-panel v-for="tooth in teethList" :key="tooth.toothId" :title="`Tooth ${tooth.toothId}`">
              <v-expansion-panel-text>
                <div class="mb-2">
                  <strong>Center Position:</strong>
                  {{tooth.centerPosition?.map((p: number) => p.toFixed(2)).join(', ') || 'N/A'}}
                </div>

                <div v-if="tooth.pairs.length > 0">
                  <h4 class="text-subtitle-2 mb-2">TRL/CAL Pairs:</h4>
                  <v-list density="compact">
                    <v-list-item v-for="(pair, index) in tooth.pairs" :key="index">
                      <template v-slot:prepend>
                        <v-icon color="primary">mdi-ruler</v-icon>
                      </template>
                      <v-list-item-title>
                        <span>Pair {{ index + 1 }} - ABLD: {{ pair.abld?.toFixed(3) || 'N/A' }}</span>
                        <v-chip v-if="pair.abld !== undefined && pair.abld !== null"
                          :color="getPeriodontalStage(pair.abld).color" size="small" class="ml-2">
                          Stage {{ getPeriodontalStage(pair.abld).stage }}
                        </v-chip>
                      </v-list-item-title>
                      <v-list-item-subtitle>
                        TRL: {{ pair.trl ? dentalStore.lengthByID[pair.trl.id]?.toFixed(2) : 'N/A' }}mm |
                        CAL: {{ pair.cal ? dentalStore.lengthByID[pair.cal.id]?.toFixed(2) : 'N/A' }}mm
                      </v-list-item-subtitle>
                    </v-list-item>
                  </v-list>
                </div>
              </v-expansion-panel-text>
            </v-expansion-panel>
          </v-expansion-panels>
        </div>
      </v-window-item>

      <v-window-item value="measurements">
        <dental-measurements-list />
      </v-window-item>
    </v-window>
  </div>
</template>

<style scoped>
.tab-header {
  font-size: 0.8rem;
}
</style>