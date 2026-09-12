/**
 * `desktop/smoke-managed.js` — the PACKAGED first-run experience, headless.
 *
 * Stages a resources dir exactly like the installed app's (runtime.tar.gz +
 * backend + frontend-dist), points app-data at a scratch dir, and boots in
 * MANAGED mode: unpack → conda-unpack → initdb → private postgres+redis →
 * migrations (0001 creates PostGIS extensions — superuser in OUR cluster) →
 * API. Then proves the stack end-to-end by CREATING A PROJECT (a real INSERT
 * through SQLAlchemy/psycopg into the bundled PostGIS). Run: `node smoke-managed.js`.
 */

'use strict';

const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');

function request(method, url, body) {
  return new Promise((resolve, reject) => {
    const data = body ? JSON.stringify(body) : null;
    const req = http.request(
      url,
      { method, headers: data ? { 'Content-Type': 'application/json' } : {} },
      (res) => {
        let out = '';
        res.on('data', (d) => (out += d));
        res.on('end', () => resolve({ status: res.statusCode, body: out }));
      },
    );
    req.on('error', reject);
    if (data) req.write(data);
    req.end();
  });
}

(async () => {
  const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'le-desktop-'));
  const resources = path.join(scratch, 'resources');
  fs.mkdirSync(resources, { recursive: true });

  // Stage the resources the installer ships.
  const here = __dirname;
  fs.copyFileSync(path.join(here, 'runtime-build', 'runtime.tar.gz'), path.join(resources, 'runtime.tar.gz'));
  fs.symlinkSync(path.resolve(here, '..', 'backend'), path.join(resources, 'backend'));
  fs.symlinkSync(path.resolve(here, '..', 'frontend', 'dist'), path.join(resources, 'frontend-dist'));
  // Source-shadowed gis/ai_engine, exactly as the installer stages them.
  fs.symlinkSync(path.resolve(here, '..', 'gis', 'src'), path.join(resources, 'gis-src'));
  fs.symlinkSync(path.resolve(here, '..', 'ai_engine', 'src'), path.join(resources, 'ai_engine-src'));

  process.env.LE_DESKTOP_APPDATA = path.join(scratch, 'appdata');
  // ★ The managed stack must not inherit the dev database/redis by accident.
  delete process.env.LE_DATABASE_URL;
  delete process.env.LE_REDIS_URL;

  const { start } = require('./boot');
  let stop = () => {};
  try {
    const t0 = Date.now();
    const boot = await start({ onStatus: (m) => console.log(`[boot] ${m}`), resources });
    stop = boot.stop;
    const base = boot.url.replace(/\/$/, '');
    console.log(`[smoke] booted in ${((Date.now() - t0) / 1000).toFixed(1)}s at ${base}`);

    const index = await request('GET', `${base}/`);
    if (index.status !== 200 || !index.body.includes('<div id="root">'))
      throw new Error(`SPA index: ${index.status}`);

    const created = await request('POST', `${base}/api/v1/projects`, {
      name: `desktop-smoke-${Date.now() % 100000}`,
    });
    if (created.status !== 201) throw new Error(`create project: ${created.status} ${created.body.slice(0, 300)}`);
    const project = JSON.parse(created.body);
    console.log(`[smoke] created project ${project.id} in the BUNDLED PostGIS`);

    const listed = await request('GET', `${base}/api/v1/projects?limit=5`);
    if (listed.status !== 200 || !listed.body.includes(project.id))
      throw new Error('project not listed back');

    console.log('MANAGED DESKTOP SMOKE: OK');
    await stop(); // ★ awaited — resolves once uvicorn/celery AND postgres/redis are down
    process.exit(0);
  } catch (err) {
    console.error('MANAGED DESKTOP SMOKE: FAILED —', String(err.message || err));
    await stop();
    process.exit(1);
  }
})();
