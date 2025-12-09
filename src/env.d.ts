/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_DICOM_WEB_URL: string;
  readonly VITE_DICOM_WEB_NAME: string;
  readonly VITE_ENABLE_REMOTE_SAVE: string;
  readonly VITE_REMOTE_SERVER_URL: string;
  readonly VITE_REMOTE_SAVE_URL: string;
  readonly VITE_HIDE_SAMPLE_DATA: string;
  readonly VITE_HIDE_DICOM_WEB: string;
  readonly VITE_FASTAPI_URL:string;
  readonly VITE_FOUNDATION_API:string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare const __VERSIONS__: Record<string, string>;
