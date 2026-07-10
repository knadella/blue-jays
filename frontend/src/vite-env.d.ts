/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_MLB_SEASON?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
