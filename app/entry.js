/**
 * The bundled boot entry. The source stays vanilla ES modules; esbuild packs
 * the boot graph into one request and leaves each view as a lazy chunk.
 */

import { boot } from "./app.js";

boot();
