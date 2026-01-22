<script setup lang="ts">
import { computed } from 'vue';
import { storeToRefs } from 'pinia';
import { useDentalStore } from '@/src/store/tools/dental';

const dentalStore = useDentalStore();
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
  <div class="pa-3">
    <!-- Empty state -->
    <div v-if="teethList.length === 0" class="text-center py-8">
      <v-icon size="64" color="grey-lighten-1" class="mb-4">mdi-tooth-outline</v-icon>
      <p class="text-body-1 text-grey-darken-1">No dental data available</p>
      <p class="text-body-2 text-grey">Click the Measurement button to load data</p>
    </div>

    <!-- Teeth list -->
    <div v-else>
      <div v-for="tooth in teethList" :key="tooth.toothId" :title="`Tooth ${tooth.toothId}`" class="mb-4 pa-3 border rounded">
        <div>
          <!-- <div class="mb-2">
            <strong>Center Position:</strong>
            {{tooth.centerPosition?.map((p: number) => p.toFixed(2)).join(', ') || 'N/A'}}
          </div> -->

          <div v-if="tooth.pairs.length > 0">
            <v-list density="compact">
              <v-list-item v-for="(pair, index) in tooth.pairs" :key="index">
                <template v-slot:prepend>
                  <v-icon color="primary">mdi-ruler</v-icon>
                </template>
                <v-list-item-title class="mb-2">
                  <!-- <span>Pair {{ index + 1 }}</span> -->
                  <span>ABLD: {{ pair.abld?.toFixed(3) || 'N/A' }}</span>
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
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.text-h6 {
  font-weight: 600;
}
</style>