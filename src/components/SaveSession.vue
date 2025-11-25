<template>
  <v-card>
    <v-card-title class="d-flex flex-row align-center">
      Saving Session State
    </v-card-title>
    <v-card-text>
      <v-form v-model="valid" @submit.prevent="saveSession">
        <v-text-field v-model="fileName" hint="The filename to use for the session state file."
          label="Session State Filename" :rules="[validFileName]" required id="session-state-filename" />
      </v-form>
    </v-card-text>
    <v-card-actions>
      <v-spacer />
      <v-btn :loading="saving" color="secondary" @click="saveSession" :disabled="!valid">
        <v-icon class="mr-2">mdi-content-save-all</v-icon>
        <span data-testid="save-session-confirm-button">Save</span>
      </v-btn>
    </v-card-actions>
  </v-card>
</template>

<script lang="ts">
import { defineComponent, onMounted, ref } from 'vue';
// import { saveAs } from 'file-saver';
import JSZip from 'jszip';
import { onKeyDown } from '@vueuse/core';
import * as dicomParser from "dicom-parser";

import { serialize } from '../io/state-file';
import { createManifest, Manifest } from '../utils/saveAnnotation';

const DEFAULT_FILENAME = 'session.volview.zip';

export default defineComponent({
  props: {
    close: {
      type: Function,
      required: true,
    },
  },
  setup(props) {
    const fileName = ref('');
    const valid = ref(true);
    const saving = ref(false);

    async function extractDicomMetadataFromZip(zipBlob: Blob): Promise<Manifest> {

      const manifest = await createManifest(zipBlob);

      return manifest;
    }

    async function saveSession() {
      if (fileName.value.trim().length >= 0) {
        saving.value = true;
        try {
          const blob = await serialize();
          // saveAs(blob, fileName.value);
          props.close();

          const manifestAndMetadata = await extractDicomMetadataFromZip(blob);

          // Call ABP API
          const response = await fetch("https://localhost:44373/api/app/annotation/save-manifest", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              // "Authorization": "Bearer " + localStorage.getItem("access_token")
            },
            body: JSON.stringify(manifestAndMetadata)
          });

          if (!response.ok) {
            // const err = await response.text();
            throw new Error("Save failed");
          }

          const result = await response.json();

          // Inform user
          alert("Manifest saved successfully. Conversion job queued!");
          console.log("Saved Manifest ID:", result.id);
        }
        catch (error) {
          console.error("Error saving annotations:", error);
          alert("Save failed:");
        }
        finally {
          saving.value = false;
        }
      }
    }

    onMounted(() => {
      // triggers form validation check so can immediately save with default value
      fileName.value = DEFAULT_FILENAME;
    });

    onKeyDown('Enter', () => {
      saveSession();
    });

    function validFileName(name: string) {
      return name.trim().length > 0 || 'Required';
    }

    return {
      saving,
      saveSession,
      fileName,
      validFileName,
      valid,
    };
  },
});
</script>
