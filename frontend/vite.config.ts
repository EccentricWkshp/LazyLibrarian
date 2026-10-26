// Builds the front end into data/ui, which LazyLibrarian serves: index.html for each of the
// front end's pages and the assets below ui/assets. The built files are committed, so a git
// install needs no Node.js, and CI checks they match this source. There are no dynamic imports,
// so everything is one bundle, and its paths are relative to the <base> LazyLibrarian puts in
// index.html, so it works below any HTTP_ROOT

import path from 'path';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const src = path.resolve(import.meta.dirname, 'src');

export default defineConfig({
  root: import.meta.dirname,
  base: './',
  plugins: [react()],
  resolve: {
    // imports from the top of src, like Sonarr's: 'Components/Page/Page'
    alias: [
      {
        find: /^(Activity|App|Components|InteractiveImport|InteractiveSearch|Styles|Utilities|Wanted|typings)\//,
        replacement: `${src}/$1/`,
      },
    ],
  },
  build: {
    outDir: path.resolve(import.meta.dirname, '../data/ui'),
    emptyOutDir: true,
    assetsDir: 'assets',
    sourcemap: false,
  },
});
