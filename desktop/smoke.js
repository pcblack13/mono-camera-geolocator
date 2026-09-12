/**
 * `desktop/smoke.js` — the whole desktop boot path, headless.
 *
 * Boots the sidecars exactly as Electron would (same `boot.js`), then proves the
 * four things the desktop window depends on:
 *   1. the API is healthy;
 *   2. `/` serves the built SPA's index.html;
 *   3. a DEEP LINK (`/projects/xyz`) also serves index.html (the client router's
 *      contract);
 *   4. an unknown API path still fails as JSON, never as HTML.
 * Then tears everything down and exits 0/1. Run: `node smoke.js`.
 */

'use strict';

const http = require('node:http');
const { start } = require('./boot');

function get(url) {
  return new Promise((resolve, reject) => {
    http
      .get(url, (res) => {
        let body = '';
        res.on('data', (d) => (body += d));
        res.on('end', () =>
          resolve({ status: res.statusCode, type: res.headers['content-type'] || '', body }),
        );
      })
      .on('error', reject);
  });
}

(async () => {
  let stop = () => {};
  try {
    const boot = await start({ onStatus: (m) => console.log(`[boot] ${m}`) });
    stop = boot.stop;
    const base = boot.url.replace(/\/$/, '');

    const health = await get(`${base}/api/v1/health/ready`);
    if (health.status !== 200) throw new Error(`health: ${health.status}`);

    const index = await get(`${base}/`);
    if (index.status !== 200 || !index.body.includes('<div id="root">'))
      throw new Error(`index: ${index.status} (${index.type})`);

    const deep = await get(`${base}/projects/00000000-0000-0000-0000-000000000000`);
    if (deep.status !== 200 || !deep.body.includes('<div id="root">'))
      throw new Error(`deep link: ${deep.status} (${deep.type})`);

    const apiMiss = await get(`${base}/api/v1/definitely-not-a-route`);
    if (apiMiss.status !== 404 || !apiMiss.type.includes('json'))
      throw new Error(`API 404 leaked HTML: ${apiMiss.status} (${apiMiss.type})`);

    console.log('DESKTOP BOOT SMOKE: OK');
    await stop(); // ★ awaited — stop() resolves only when children AND services are down
    process.exit(0);
  } catch (err) {
    console.error('DESKTOP BOOT SMOKE: FAILED —', String(err.message || err));
    await stop();
    process.exit(1);
  }
})();
