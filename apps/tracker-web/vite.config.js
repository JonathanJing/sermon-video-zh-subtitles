import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';

// The browser bundle imports the shared projection contract from
// packages/tracker-contract, outside this app's root. `vite build` follows
// the import; the dev server also needs the repository root allow-listed.
export default defineConfig({
  server: { fs: { allow: [fileURLToPath(new URL('../..', import.meta.url))] } },
});
