import { serialize } from '@/src/io/state-file';
import { useMessageStore } from '@/src/store/messages';
import { defineStore } from 'pinia';
import { ref } from 'vue';
import { createManifest, getVtiFilesZip } from '../utils/saveAnnotation';
import JSZip from 'jszip';
import { get } from '@kitware/vtk.js/macros';

const useRemoteSaveStateStore = defineStore('remoteSaveState', () => {
  const saveUrl = ref('');
  const isSaving = ref(false);

  const messageStore = useMessageStore();

  const setSaveUrl = (url: string) => {
    saveUrl.value = url;
  };

  async function extractDicomMetadataFromZip(zipBlob: Blob): Promise<Manifest> {
    const manifest = await createManifest(zipBlob);

    return manifest;
  }

  const saveState = async () => {
    if (!saveUrl.value || isSaving.value) return;
    try {
      isSaving.value = true;

      const blob = await serialize();

      const manifestAndMetadata = await extractDicomMetadataFromZip(blob);
      const { VITE_FOUNDATION_API } = import.meta.env;

      // Call ABP API - save manifest
      const saveManifestUrl = `${VITE_FOUNDATION_API}/save-manifest`;
      const response = await fetch(saveManifestUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(manifestAndMetadata),
      });

      // Call ABP API - save segmentation
      const saveSegmentationFormData = await getVtiFilesZip(
        blob,
        manifestAndMetadata.studyInstanceUID
      );
      const saveSegmentationUrl = `${VITE_FOUNDATION_API}/save-segmentation`;
      const segmentationResponse = await fetch(saveSegmentationUrl, {
        method: 'POST',
        body: saveSegmentationFormData,
      });

      if (!response.ok && !segmentationResponse.ok) {
        throw new Error('Save failed');
      }

      const result = await response.json();

      console.log('Saved Manifest ID:', result.id);
    } catch (error) {
      messageStore.addError('Save Failed with error', `Failed from: ${error}`);
    } finally {
      isSaving.value = false;
    }
  };

  return {
    saveUrl,
    setSaveUrl,
    isSaving,
    saveState,
  };
});

export default useRemoteSaveStateStore;
