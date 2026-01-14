<script setup lang="ts">
import { ref } from 'vue';
import DentalControls from './DentalControls.vue';
import DentalMeasurementsList from './DentalMeasurementsList.vue';

const tab = ref('teeth');
</script>

<template>
  <div class="overflow-y-auto mx-2 fill-height">
    <v-tabs v-model="tab" align-tabs="center" density="compact" class="my-1">
      <v-tab value="teeth" class="tab-header">Teeth</v-tab>
      <v-tab value="measurements" class="tab-header">Measurements</v-tab>
    </v-tabs>

    <v-window v-model="tab">
      <v-window-item value="teeth">
        <dental-controls />
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