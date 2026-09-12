/**
 * `build/make-icons.js` — render `desktop/icon.svg` into the platform icon set.
 *
 * ★ Run at icon-change time, not at build time; the outputs are COMMITTED
 *   (electron-builder reads them from this `build/` dir automatically):
 *     build/icon.png  — 512px, Linux (deb menu entry + AppImage)
 *     build/icon.ico  — 16…256px, Windows (exe, installer, shortcuts)
 *
 *   Usage: node build/make-icons.js
 */

'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { Resvg } = require('@resvg/resvg-js');
// png-to-ico ships as an ES-module default export under CJS interop.
const pngToIcoModule = require('png-to-ico');
const pngToIco = pngToIcoModule.default ?? pngToIcoModule;

const here = __dirname;
const svg = fs.readFileSync(path.join(here, '..', 'icon.svg'), 'utf8');

function renderPng(size) {
  return new Resvg(svg, { fitTo: { mode: 'width', value: size } }).render().asPng();
}

(async () => {
  fs.writeFileSync(path.join(here, 'icon.png'), renderPng(512));
  const icoSizes = [16, 24, 32, 48, 64, 128, 256];
  const ico = await pngToIco(icoSizes.map(renderPng));
  fs.writeFileSync(path.join(here, 'icon.ico'), ico);
  console.log(`icons written: icon.png (512), icon.ico (${icoSizes.join(',')})`);
})();
