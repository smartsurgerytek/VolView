<script setup lang="ts">  
import { computed } from 'vue';  
import { useDentalStore } from '@/src/store/tools/dental';  
  
const props = defineProps<{  
  tool: any;  
}>();  
  
const dentalStore = useDentalStore();  
  
const length = computed(() => dentalStore.lengthByID[props.tool.id]);  
const pairInfo = computed(() => {  
  if (!props.tool.toothId || !props.tool.pairId) return null;  
    
  const pairs = dentalStore.getToothPairs(props.tool.toothId);  
  const pair = pairs.find(p =>   
    p.trl?.id === props.tool.id || p.cal?.id === props.tool.id  
  );  
    
  return pair;  
});
</script>  
  
<template>  
  <div class="dental-details">  
    <div class="detail-row">  
      <span class="label">Type:</span>  
      <span class="value">{{ tool.type }}</span>  
    </div>  
      
    <div class="detail-row">  
      <span class="label">Tooth ID:</span>  
      <span class="value">{{ tool.toothId || 'N/A' }}</span>  
    </div>  
      
    <div class="detail-row">  
      <span class="label">Length:</span>  
      <span class="value">{{ length?.toFixed(2) || 'N/A' }} mm</span>  
    </div>  
      
    <div v-if="pairInfo" class="detail-row">  
      <span class="label">ABLD:</span>  
      <span class="value">{{ pairInfo.abld?.toFixed(3) || 'N/A' }}</span>  
    </div>  
      
    <div class="detail-row">  
      <span class="label">Slice:</span>  
      <span class="value">{{ tool.slice }}</span>  
    </div>  
      
    <div class="detail-row">  
      <span class="label">Axis:</span>  
      <span class="value">{{ tool.axis || 'Unknown' }}</span>  
    </div>  
  </div>  
</template>  
  
<style scoped>  
.dental-details {  
  display: flex;  
  flex-direction: column;  
  gap: 4px;  
}  
  
.detail-row {  
  display: flex;  
  justify-content: space-between;  
  font-size: 0.875rem;  
}  
  
.label {  
  font-weight: 500;  
  color: var(--v-theme-on-surface-variant);  
}  
  
.value {  
  font-family: monospace;  
}  
</style>