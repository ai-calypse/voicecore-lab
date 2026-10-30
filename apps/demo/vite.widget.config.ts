import { defineConfig } from "vite";

// The embeddable widget as one classic script: public/embed/voicecore.js
export default defineConfig({
  publicDir: false,
  build: {
    outDir: "public/embed",
    emptyOutDir: true,
    lib: { entry: "src/widget.ts", name: "VoiceCoreWidget", formats: ["iife"], fileName: () => "voicecore.js" },
  },
});
