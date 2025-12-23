import { defineStore } from 'pinia';
import { ref } from 'vue';

export const useImageSelectionStore = defineStore('imageSelection', () => {
  const selectedImageIDs = ref<string[]>([]);

  function setSelectedImageIDs(imageIDs: string[]) {
    selectedImageIDs.value = imageIDs;
  }

  function clearSelectedImageIDs() {
    selectedImageIDs.value = [];
  }

  return {
    selectedImageIDs,
    setSelectedImageIDs,
    clearSelectedImageIDs,
  };
});
