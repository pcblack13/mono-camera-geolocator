/**
 * `desktop/main.js` — the Electron entry: windows only, no boot logic.
 *
 * ★ Everything that can fail (venv, migrations, ports, health) lives in `boot.js`,
 *   which is plain Node and smoke-tested headlessly. This file's whole job:
 *   1. single-instance lock — two copies would fight over the sidecars;
 *   2. a branded splash while the sidecars boot, with errors shown IN it;
 *   3. the app window on the local origin once the API is healthy;
 *   4. killing the sidecars on quit, every path.
 *
 * ★ THE SPLASH SPEAKS USER, THE LOG SPEAKS ENGINEER. `boot.js` narrates in
 *   technical stages ("applying database migrations…"), which is exactly right for
 *   the log and exactly wrong for a customer's first launch. `phaseFor()` folds
 *   those stages into three friendly phases with a progress feel; the verbatim
 *   technical line still goes to stdout for support. ERRORS are the exception —
 *   they show their real text, because "something went wrong" with no detail is a
 *   support call with no content.
 */

'use strict';

const { execFile } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const { app, BrowserWindow, dialog, ipcMain } = require('electron');
const zoomRules = require('./zoom');
const { start } = require('./boot');
const { appDataDir } = require('./runtime');

// ── the boot log file ───────────────────────────────────────────────────────────
/**
 * ★ WHY A FILE: on Windows a GUI Electron app detaches from the console, so the
 *   stdout narration is unreachable ("the log file is empty") and the splash was
 *   the ONLY witness to a boot failure — unscrollable screenshots as bug reports.
 *   Every [boot] line and the full failure text now also land in
 *   `<app-data>/boot.log`, truncated at each launch so it is always THIS run.
 */
const BOOT_LOG = (() => {
  // ★ Attach mode (verification) must not overwrite the installed app's log of
  //   ITS last boot — that file is what support reads after a failure.
  if (process.env.LE_DESKTOP_ATTACH_URL) return null;
  try {
    const dir = appDataDir();
    fs.mkdirSync(dir, { recursive: true });
    const file = path.join(dir, 'boot.log');
    fs.writeFileSync(file, `MonoCameraGeolocator ${app.getVersion?.() ?? ''} — boot log\n`);
    return file;
  } catch {
    return null; // no writable app-data — stdout-only, exactly as before
  }
})();

function logBoot(line) {
  console.log(line);
  if (!BOOT_LOG) return;
  try {
    fs.appendFileSync(BOOT_LOG, `${new Date().toISOString()} ${line}\n`);
  } catch {
    /* logging must never break the boot */
  }
}

// ── native file picking (out-of-process) ───────────────────────────────────────
/**
 * ★ WHY NOT `<input type=file>` OR `dialog.showOpenDialog` ALONE: Chromium's
 *   in-process GTK chooser is broken on modern GNOME in BOTH GTK modes — GTK4
 *   needs two attempts to accept a file, GTK3 SIGTRAPs the entire app while
 *   browsing a folder (both reproduced in the field on 1.2.1/1.2.2). An
 *   out-of-process picker (zenity — GNOME's own dialog tool, spawned as a
 *   separate process) cannot take the app down no matter what GTK does. Where
 *   zenity is absent (Windows, non-GNOME distros), Electron's dialog is the
 *   fallback — those platforms never showed the bug.
 */
function zenityPick(filters, multiple) {
  return new Promise((resolve) => {
    const args = ['--file-selection', '--title=Select a file'];
    if (multiple) args.push('--multiple', '--separator=\n');
    for (const f of filters ?? []) {
      const globs = f.extensions.map((e) => (e === '*' ? '*' : `*.${e}`)).join(' ');
      args.push(`--file-filter=${f.name} | ${globs}`);
    }
    // ★ WHITELIST env, not inherit: a launcher's environment (snap-packaged
    //   IDEs, AppImages) leaks LD_LIBRARY_PATH / GDK_PIXBUF_MODULE_FILE / GTK
    //   module paths that point the system zenity at incompatible libraries —
    //   symbol lookup error, exit 127 (reproduced under a snap VSCode shell).
    //   zenity is a system binary: it gets the system's own env and nothing else.
    const env = {};
    for (const key of [
      'HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'TZ',
      'DISPLAY', 'XAUTHORITY', 'WAYLAND_DISPLAY',
      'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS', 'XDG_CURRENT_DESKTOP', 'XDG_SESSION_TYPE',
    ]) {
      if (process.env[key] !== undefined) env[key] = process.env[key];
    }
    env.PATH = '/usr/local/bin:/usr/bin:/bin';
    execFile('zenity', args, { maxBuffer: 1024 * 1024, env }, (err, stdout) => {
      if (!err) return resolve(stdout.split('\n').map((s) => s.trim()).filter(Boolean));
      if (err.code === 1) return resolve([]); // exit 1 = user cancelled — a real answer
      resolve(null); // absent, crashed, or broken env — let the Electron dialog try
    });
  });
}

async function electronPick(filters, multiple) {
  const options = {
    properties: multiple ? ['openFile', 'multiSelections'] : ['openFile'],
    filters,
  };
  // A parent window is optional — passing undefined for it throws.
  const win = BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0];
  const r = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options);
  return r.canceled ? [] : r.filePaths;
}

/** The shared front half of both pickers: zenity where it exists, dialog elsewhere. */
async function pickPaths(filters, multiple) {
  return process.platform === 'linux'
    ? ((await zenityPick(filters, multiple)) ?? (await electronPick(filters, multiple)))
    : await electronPick(filters, multiple);
}

// ★ CEILING FOR THE BYTES-OVER-IPC ROUTE. `fs.readFileSync` hard-fails above 2 GiB
//   (ERR_FS_FILE_TOO_LARGE), and even below that the bytes are copied several times
//   over (Buffer → IPC clone → renderer Uint8Array → File → XHR body). 1 GiB is a
//   safe ceiling for photos/CSVs/KML; anything bigger must travel by PATH
//   (`le:pick-paths` + the API's `source_path` mode), which never loads the file
//   into memory at all. Before this guard existed, a 3.8 GB DEM pick threw inside
//   the silent catch below and simply DID NOTHING — the field report on 1.2.x.
const MAX_IPC_FILE_BYTES = 1024 * 1024 * 1024;

ipcMain.handle('le:pick-files', async (_event, filters, multiple) => {
  const paths = await pickPaths(filters, multiple);
  const files = [];
  const skipped = [];
  for (const p of paths) {
    try {
      const size = fs.statSync(p).size;
      if (size > MAX_IPC_FILE_BYTES) {
        skipped.push({
          name: path.basename(p),
          reason:
            `${(size / 1024 ** 3).toFixed(1)} GiB is too large to load into memory — ` +
            'this upload supports files up to 1 GiB',
        });
        continue;
      }
      files.push({ name: path.basename(p), data: fs.readFileSync(p) });
    } catch (err) {
      // ★ Report, never swallow: a silently skipped file looks like a click that
      //   did nothing, and nobody can debug a nothing.
      skipped.push({ name: path.basename(p), reason: String((err && err.code) || err) });
    }
  }
  return { files, skipped };
});

// ★ The PATH picker: same dialogs, but returns {name, path, size} without reading a
//   byte. This is how multi-GB files (DEMs, videos) reach the backend — the API and
//   the renderer live on the same machine, so the backend opens the path directly.
ipcMain.handle('le:pick-paths', async (_event, filters, multiple) => {
  const paths = await pickPaths(filters, multiple);
  const out = [];
  for (const p of paths) {
    try {
      out.push({ name: path.basename(p), path: p, size: fs.statSync(p).size });
    } catch {
      // stat failed — unreadable; leave it out
    }
  }
  return out;
});

// ── native FOLDER picking ───────────────────────────────────────────────────────
/** Pick a directory with zenity; resolves to a path, '' on cancel, null if absent. */
function zenityPickDir() {
  return new Promise((resolve) => {
    const env = {};
    for (const key of [
      'HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'TZ',
      'DISPLAY', 'XAUTHORITY', 'WAYLAND_DISPLAY',
      'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS', 'XDG_CURRENT_DESKTOP', 'XDG_SESSION_TYPE',
    ]) {
      if (process.env[key] !== undefined) env[key] = process.env[key];
    }
    env.PATH = '/usr/local/bin:/usr/bin:/bin';
    execFile(
      'zenity',
      ['--file-selection', '--directory', '--title=Choose a folder to save into'],
      { maxBuffer: 1024 * 1024, env },
      (err, stdout) => {
        if (!err) return resolve(stdout.trim());
        if (err.code === 1) return resolve(''); // cancelled
        resolve(null); // zenity absent/broken — fall back to Electron
      },
    );
  });
}

async function electronPickDir() {
  const options = { properties: ['openDirectory', 'createDirectory'] };
  const win = BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0];
  const r = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options);
  return r.canceled || r.filePaths.length === 0 ? '' : r.filePaths[0];
}

// ★ Returns an absolute folder path, '' if the user cancelled, or null when there is
//   no native shell at all (plain browser — the caller keeps the folder unset).
ipcMain.handle('le:pick-directory', async () => {
  if (process.platform === 'linux') {
    const viaZenity = await zenityPickDir();
    if (viaZenity !== null) return viaZenity;
  }
  return electronPickDir();
});

// ★ Force GTK3 on Linux. Electron ≥ 33 auto-picks GTK4 on GNOME ≥ 46, and the
//   GTK4 + xdg-portal file chooser is flaky there: the dialog blanks/reloads on
//   first open and needs a second attempt to pick a file (field report, Ubuntu
//   24.04). GTK3 dialogs are the battle-tested path. Must run before app.ready.
if (process.platform === 'linux') {
  app.commandLine.appendSwitch('gtk-version', '3');
}

let stopSidecars = null;
let stopSidecarsSync = null;

// ── boot phases: technical narration → customer language ───────────────────────
/**
 * Order matters twice: the first matching rule wins, and `step` drives the
 * progress feel (a later phase never moves the bar backwards).
 */
const PHASES = [
  {
    match: /first run|unpack|relocat/i,
    step: 1,
    title: 'Setting up for first use',
    detail: 'This one-time step takes about a minute.',
  },
  {
    match: /database|postgres|redis|migrations|leftover/i,
    step: 2,
    title: 'Preparing your workspace',
    detail: 'Your projects and survey data are kept safely on this computer.',
  },
  {
    match: /API|worker|ready/i,
    step: 3,
    title: 'Almost ready',
    detail: 'Starting the application…',
  },
];

function phaseFor(message) {
  for (const phase of PHASES) {
    if (phase.match.test(message)) return phase;
  }
  return { step: 0, title: 'Starting Mono Camera Geolocator', detail: ' ' };
}

/**
 * The splash: branded, animated, and free of backend vocabulary.
 *
 * ★ THE SAME PALETTE AS THE APP. Colours here are the dark theme's tokens
 *   (`frontend/src/theme/tokens.css`): base `#0b0f14`, elevated `#121821`, text
 *   `#e6edf5` / `#93a1b3`, the single instrument-cyan accent `#35c8d8`, and the
 *   confidence green `#4ade80` for the survey point. The mark is the compass the
 *   app's own hero wears, so the window that opens looks like the one it opened.
 */
function createStatusWindow() {
  const win = new BrowserWindow({
    width: 460,
    height: 300,
    resizable: false,
    maximizable: false,
    fullscreenable: false,
    autoHideMenuBar: true,
    title: 'Mono Camera Geolocator',
    backgroundColor: '#0b0f14',
  });
  const html = `<!doctype html><meta charset="utf-8"><title>Mono Camera Geolocator</title>
<style>
  :root { color-scheme: dark; }
  body {
    margin: 0; height: 100vh; display: grid; place-items: center;
    background:
      radial-gradient(70% 90% at 85% 0%, rgba(53, 200, 216, .16) 0%, transparent 60%),
      linear-gradient(180deg, #121821 0%, #0b0f14 100%);
    color: #e6edf5; font: 14px/1.5 'Inter', system-ui, sans-serif;
    -webkit-user-select: none; user-select: none; overflow: hidden;
    position: relative;
  }
  /* contour lines, the instrument's ground — the hero draws the same */
  body::before {
    content: ''; position: absolute; inset: 0; pointer-events: none;
    background-image:
      radial-gradient(120% 120% at 100% 0%, transparent 38%, rgba(53, 200, 216, .09) 38.5%, transparent 39.5%),
      radial-gradient(120% 120% at 100% 0%, transparent 48%, rgba(53, 200, 216, .09) 48.5%, transparent 49.5%),
      radial-gradient(120% 120% at 100% 0%, transparent 58%, rgba(53, 200, 216, .09) 58.5%, transparent 59.5%),
      radial-gradient(120% 120% at 100% 0%, transparent 68%, rgba(53, 200, 216, .08) 68.5%, transparent 69.5%);
  }
  .card { text-align: center; width: 380px; padding: 0 16px; position: relative; }

  /* ── the mark: the compass, and a survey point that pulses ──────────── */
  .mark { width: 64px; height: 64px; margin: 0 auto 14px; display: block; }
  .mark .tile { fill: rgba(53, 200, 216, .14); stroke: #2b3644; }
  .mark .compass { fill: #35c8d8; }
  .mark .gcp { fill: #4ade80; }
  .mark .gcp-pulse {
    fill: none; stroke: #4ade80; stroke-width: 2; opacity: 0;
    transform-origin: 50px 14px; animation: pulse 2.4s ease-out infinite;
  }
  @keyframes pulse {
    0%   { opacity: .8; transform: scale(.4); }
    70%  { opacity: 0;  transform: scale(1.6); }
    100% { opacity: 0;  transform: scale(1.6); }
  }

  .eyebrow {
    font: 600 10px/1 ui-monospace, 'JetBrains Mono', monospace; letter-spacing: .12em;
    color: #35c8d8; margin-bottom: 8px;
  }
  .word { font-size: 22px; font-weight: 700; letter-spacing: -.3px; margin-bottom: 22px; }

  /* ── progress: a real track that FILLS by phase, with a live sheen ───── */
  .track {
    height: 4px; border-radius: 999px; background: #1e2731;
    overflow: hidden; margin: 0 24px 16px; position: relative;
  }
  .fill {
    height: 100%; width: 8%; border-radius: 999px;
    background: linear-gradient(90deg, #23a9b8, #55d8e6);
    transition: width .8s cubic-bezier(.4, 0, .2, 1);
    position: relative; overflow: hidden;
  }
  .fill::after {
    content: ''; position: absolute; inset: 0;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,.35), transparent);
    animation: sheen 1.6s ease-in-out infinite;
  }
  @keyframes sheen { from { transform: translateX(-100%); } to { transform: translateX(100%); } }

  .title  { font-size: 15px; font-weight: 600; margin-bottom: 4px; }
  .detail { font-size: 12.5px; color: #93a1b3; min-height: 1.5em; }

  /* ── error state: honest text, calm presentation ─────────────────────── */
  .error { display: none; text-align: left; }
  body.failed .error { display: block; }
  body.failed .track, body.failed .title, body.failed .detail { display: none; }
  .error h2 { font-size: 15px; margin: 0 0 8px; color: #f87171; }
  .error pre {
    margin: 0 0 10px; padding: 10px 12px; border-radius: 8px;
    background: #090d12; border: 1px solid rgba(248, 113, 113, .35); color: #e6edf5;
    font: 12px/1.45 ui-monospace, monospace; white-space: pre-wrap; word-break: break-word;
    max-height: 110px; overflow: auto;
    /* ★ Selectable, overriding the body's user-select:none — a support message
       nobody can copy is a screenshot-only bug report (learned on Windows). */
    -webkit-user-select: text; user-select: text; cursor: text;
  }
  .error p { margin: 0; font-size: 12.5px; color: #93a1b3; }
</style>
<body>
  <div class="card">
    <svg class="mark" viewBox="0 0 64 64" aria-hidden="true">
      <rect class="tile" x="1" y="1" width="62" height="62" rx="14"/>
      <g transform="translate(12 12) scale(1.6667)">
        <path class="compass" d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2m0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8m-5.5-2.5 7.51-3.49L17.5 6.5 9.99 9.99zm5.5-6.6c.61 0 1.1.49 1.1 1.1s-.49 1.1-1.1 1.1-1.1-.49-1.1-1.1.49-1.1 1.1-1.1"/>
      </g>
      <circle class="gcp-pulse" cx="50" cy="14" r="7"/>
      <circle class="gcp" cx="50" cy="14" r="4.5"/>
    </svg>
    <div class="eyebrow">FIELD PHOTOGRAMMETRY · OFFLINE-FIRST</div>
    <div class="word">Mono Camera Geolocator</div>
    <div class="track"><div class="fill" id="fill"></div></div>
    <div class="title"  id="title">Starting Mono Camera Geolocator</div>
    <div class="detail" id="detail">&nbsp;</div>
    <div class="error">
      <h2>Mono Camera Geolocator could not start</h2>
      <pre id="errtext"></pre>
      <p>Close this window and launch again. If it keeps happening, send the text
         above to support.</p>
    </div>
  </div>
  <script>
    const WIDTHS = { 0: '8%', 1: '35%', 2: '70%', 3: '92%' };
    let best = 0;
    window.setPhase = (step, title, detail) => {
      best = Math.max(best, step); // the bar never moves backwards
      document.getElementById('fill').style.width = WIDTHS[best] || '92%';
      document.getElementById('title').textContent = title;
      document.getElementById('detail').textContent = detail;
    };
    window.setFailed = (text) => {
      document.body.classList.add('failed');
      document.getElementById('errtext').textContent = text;
    };
  </script>
</body>`;
  win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
  return win;
}

function setStatus(win, message) {
  // The verbatim technical line still reaches the log — support needs it.
  logBoot(`[boot] ${message}`);
  if (win.isDestroyed()) return;
  const phase = phaseFor(message);
  win.webContents
    .executeJavaScript(
      `window.setPhase(${phase.step}, ${JSON.stringify(phase.title)}, ${JSON.stringify(phase.detail)});`,
    )
    .catch(() => {});
}

function setFailed(win, message) {
  logBoot(`BOOT FAILED:\n${message}`);
  if (win.isDestroyed()) return;
  // ★ Name the log file IN the error: the splash may be photographed, but the
  //   full text is sitting on disk, and the message says exactly where.
  const shown = BOOT_LOG ? `${message}\n\n(This message is saved in: ${BOOT_LOG})` : message;
  win.webContents
    .executeJavaScript(`window.setFailed(${JSON.stringify(shown)});`)
    .catch(() => {});
}

// ── display size: page zoom for big screens ─────────────────────────────────────
//
// ★ A 50-INCH TV draws the app at laptop size unless someone scales it. The
//   preference lives in userData/display.json ('auto' or a factor); 'auto' asks
//   `zoom.js` what the window's CURRENT display deserves. Applied to every app
//   window (the popped-out map included), on load and whenever it changes;
//   Ctrl + / Ctrl − / Ctrl 0 step it from the keyboard without a menu bar.

const DISPLAY_PREFS = () => path.join(app.getPath('userData'), 'display.json');

function readZoomPreference() {
  try {
    const raw = JSON.parse(fs.readFileSync(DISPLAY_PREFS(), 'utf8'));
    return zoomRules.normalisePreference(raw && raw.zoom);
  } catch {
    return 'auto';
  }
}

function writeZoomPreference(preference) {
  try {
    fs.writeFileSync(DISPLAY_PREFS(), JSON.stringify({ zoom: preference }, null, 2));
  } catch (err) {
    logBoot(`[zoom] could not save the display preference: ${err.message || err}`);
  }
}

/** What 'auto' means for the display this window is on right now. */
function autoZoomForWindow(win) {
  const { screen } = require('electron');
  const display = win && !win.isDestroyed()
    ? screen.getDisplayMatching(win.getBounds())
    : screen.getPrimaryDisplay();
  return zoomRules.autoZoomFor(display.size);
}

function zoomInfoFor(win) {
  const preference = readZoomPreference();
  const auto = autoZoomForWindow(win);
  const zoom = preference === 'auto' ? auto : preference;
  return { preference, zoom, auto, steps: zoomRules.ZOOM_STEPS };
}

function applyZoom(win) {
  if (!win || win.isDestroyed()) return;
  const info = zoomInfoFor(win);
  const wc = win.webContents;
  if (Math.abs(wc.getZoomFactor() - info.zoom) > 1e-6) wc.setZoomFactor(info.zoom);
  wc.send('le:zoom-changed', info);
}

function applyZoomEverywhere() {
  for (const win of BrowserWindow.getAllWindows()) applyZoom(win);
}

/** Give a window the zoom behaviour: applied on load, stepped from the keyboard. */
function attachZoom(win) {
  const wc = win.webContents;
  wc.on('did-finish-load', () => applyZoom(win));
  // ★ A window dragged onto the TV re-reads 'auto' for that display.
  win.on('move', () => {
    if (readZoomPreference() === 'auto') applyZoom(win);
  });
  // ★ Ctrl + / − / 0 are handled in the RENDERER (`useDisplayZoomShortcuts`),
  //   which asks for a step over IPC — one path for the keyboard and the menu,
  //   and one that injected/automated input reaches as well.
  // The popped-out map (and any other window the policy allows) zooms alike.
  wc.on('did-create-window', (child) => attachZoom(child));
}

ipcMain.handle('le:zoom-get', (event) => zoomInfoFor(BrowserWindow.fromWebContents(event.sender)));
ipcMain.handle('le:zoom-set', (event, preference) => {
  writeZoomPreference(zoomRules.normalisePreference(preference));
  applyZoomEverywhere();
  return zoomInfoFor(BrowserWindow.fromWebContents(event.sender));
});
ipcMain.handle('le:zoom-step', (event, direction) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  const current = win && !win.isDestroyed() ? win.webContents.getZoomFactor() : 1;
  writeZoomPreference(zoomRules.stepZoom(current, Number(direction) > 0 ? 1 : -1));
  applyZoomEverywhere();
  return zoomInfoFor(win);
});

function createAppWindow(url) {
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 960,
    minHeight: 640,
    autoHideMenuBar: true,
    backgroundColor: '#0b0f14',
    title: 'Mono Camera Geolocator',
    webPreferences: {
      // The UI talks to the local API over plain HTTP on 127.0.0.1 — no Node in
      // the renderer. The preload exposes exactly ONE capability (ask the user
      // to pick a file — see preload.js for why the in-page chooser is banned);
      // everything else runs exactly as in a browser.
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, 'preload.js'),
    },
  });
  // ★ A CONTENT SECURITY POLICY for the renderer. Scripts only from the app's own
  //   origin (no eval, no inline); styles allow inline because Emotion/MUI inject
  //   them; images, media and connections stay open to any host because tiles,
  //   LAN cameras and RTSP re-streams live on arbitrary addresses. Workers from
  //   blob: for MapLibre. Applied to the app's own documents only.
  const CSP = [
    "default-src 'self' http://127.0.0.1:* http://localhost:*",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: http: https:",
    "media-src 'self' blob: http: https:",
    "connect-src 'self' http: https: ws: wss:",
    "worker-src 'self' blob:",
    "font-src 'self' data:",
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
  ].join('; ');
  win.webContents.session.webRequest.onHeadersReceived((details, callback) => {
    if (details.resourceType !== 'mainFrame' && details.resourceType !== 'subFrame') {
      callback({ responseHeaders: details.responseHeaders });
      return;
    }
    callback({
      responseHeaders: { ...details.responseHeaders, 'Content-Security-Policy': [CSP] },
    });
  });
  // ★ THE APP OPENS EXACTLY ONE KIND OF WINDOW — the camera monitor's satellite
  //   map, popped out so it can live on a second screen (`/monitor/cameras/<id>/map`,
  //   same origin, same CSP). Every other window.open is a link we did not write,
  //   and is denied as before.
  const appOrigin = new URL(url).origin;
  win.webContents.setWindowOpenHandler(({ url: target }) => {
    let parsed;
    try {
      parsed = new URL(target);
    } catch {
      return { action: 'deny' };
    }
    const isMapWindow =
      parsed.origin === appOrigin && /^\/monitor\/cameras\/[^/]+\/map$/.test(parsed.pathname);
    if (!isMapWindow) return { action: 'deny' };
    return {
      action: 'allow',
      overrideBrowserWindowOptions: {
        width: 1000,
        height: 760,
        minWidth: 480,
        minHeight: 360,
        autoHideMenuBar: true,
        backgroundColor: '#0b0f14',
        title: 'Satellite map — Mono Camera Geolocator',
        webPreferences: {
          contextIsolation: true,
          nodeIntegration: false,
          preload: path.join(__dirname, 'preload.js'),
        },
      },
    };
  });
  attachZoom(win);
  win.loadURL(url);
  return win;
}

// ── single instance ─────────────────────────────────────────────────────────────
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    const [win] = BrowserWindow.getAllWindows();
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });

  app.whenReady().then(async () => {
    // ★ ATTACH MODE — verification and development only. With
    //   LE_DESKTOP_ATTACH_URL set, the REAL app window (its CSP, its window
    //   policy, its preload) opens on an app that is already running — no
    //   sidecars are booted, nothing is stopped on exit. Pair it with
    //   --user-data-dir so it never fights the installed app's instance lock.
    const attachUrl = process.env.LE_DESKTOP_ATTACH_URL;
    if (attachUrl) {
      logBoot(`[boot] attach mode: ${attachUrl}`);
      createAppWindow(attachUrl);
      return;
    }
    const status = createStatusWindow();
    try {
      const { url, stop, stopSync } = await start({
        onStatus: (msg) => setStatus(status, msg),
        // ★ Packaged → the resources dir carries runtime.tar.gz + backend +
        //   frontend-dist and boot.js switches to MANAGED mode (private
        //   postgres/redis from the bundled runtime). Unpackaged → dev mode.
        resources: app.isPackaged ? process.resourcesPath : null,
      });
      stopSidecars = stop;
      stopSidecarsSync = stopSync ?? null;
      const main = createAppWindow(url);
      main.once('ready-to-show', () => {
        if (!status.isDestroyed()) status.close();
      });
      // Belt and braces: if ready-to-show never fires, don't strand the splash.
      setTimeout(() => {
        if (!status.isDestroyed()) status.close();
      }, 8000);
    } catch (err) {
      setFailed(status, String(err.message || err));
    }
  });
}

// ── teardown: every exit path stops the sidecars ────────────────────────────────
app.on('window-all-closed', () => {
  app.quit();
});
// ★ HOLD THE QUIT until the sidecars are actually down. The previous version fired
//   SIGTERM and left the SIGKILL escalation + postgres/redis stop on an unref'd
//   timer inside boot.js — the process exited before it ever ran, so postgres and
//   redis outlived every normal close ("the laptop is slow even after closing").
//   preventDefault() pauses the quit, the awaited stop() takes it all down (a few
//   hundred ms; pg_ctl stop is the long pole), and app.exit() resumes the quit.
let quitting = false;
let sidecarsDown = false;
function shutdownAndExit() {
  if (quitting) return;
  quitting = true;
  Promise.resolve()
    .then(() => stopSidecars?.())
    .catch(() => {})
    .then(() => {
      sidecarsDown = true;
      app.exit(0); // bypasses before-quit — no loop
    });
}
app.on('before-quit', (event) => {
  if (sidecarsDown || !stopSidecars) return;
  // ★ HOLD EVERY QUIT until the sidecars are actually down — INCLUDING one that
  //   arrives while a stop is already in flight. The old guard (`if (quitting)
  //   return`) let Chromium's own SIGINT-driven quit sail past preventDefault while
  //   our async stop() was mid-teardown: Electron exited, the SIGTERM→SIGKILL
  //   escalation died with it, and a celery stuck in broker-reconnect survived as
  //   an orphan (field report). shutdownAndExit() is idempotent, so re-entering
  //   here just keeps the quit parked until the ONE teardown resolves.
  event.preventDefault();
  shutdownAndExit();
});
// ★ Ctrl+C in the launching terminal (run-desktop.sh, npm start). The sidecars sit
//   in their OWN process groups — which is what lets stop() group-kill them, and
//   also means the terminal's SIGINT no longer reaches them by itself. Without
//   this handler a Ctrl+C orphaned the whole family; the leftover celery then
//   latched onto the NEXT session's redis and spammed reconnect errors when it
//   stopped (field report). Same graceful path as closing the window.
// ★ A SECOND signal while the graceful stop runs = "I mean it": synchronous
//   SIGKILL of everything + immediate exit, instead of appearing to hang.
for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => {
    if (quitting) {
      try {
        stopSidecarsSync?.();
      } catch {
        /* best effort */
      }
      app.exit(1);
      return;
    }
    shutdownAndExit();
  });
}
// Last resort (crash paths that skip before-quit): synchronous, no grace period.
process.on('exit', () => {
  stopSidecarsSync?.();
});
