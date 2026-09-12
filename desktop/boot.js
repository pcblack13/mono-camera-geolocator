/**
 * `desktop/boot.js` — the sidecar manager, deliberately Electron-free.
 *
 * ★ EVERYTHING THAT CAN FAIL LIVES HERE, and none of it needs a window: find a free
 *   port, run migrations, start the API (serving the built frontend) and the Celery
 *   worker, poll health, and tear the whole family down on exit. Keeping it plain
 *   Node means `smoke.js` can exercise the entire boot path headlessly — the
 *   Electron layer on top is just windows.
 *
 * ★ THE WORKER IS OPTIONAL by the backend's own design (uploads never fail because
 *   the worker is down; it powers exports + thumbnails). `LE_DESKTOP_WORKER=0`
 *   skips it; a missing Redis degrades exactly as it does in dev.
 */

'use strict';

const { spawn, spawnSync } = require('node:child_process');
const http = require('node:http');
const net = require('node:net');
const path = require('node:path');
const fs = require('node:fs');

const { resourcesDir, startManaged } = require('./runtime');

const ROOT = path.resolve(__dirname, '..');
const BACKEND = path.join(ROOT, 'backend');
const FRONTEND_DIST = path.join(ROOT, 'frontend', 'dist');
const PYTHON =
  process.env.LE_DESKTOP_PYTHON || path.join(BACKEND, 'venv', 'bin', 'python');

// ★ 120 s, not 60: a FIRST Windows boot imports numpy/cv2/rasterio while Defender
//   real-time scanning walks the freshly unpacked runtime — the API can take well
//   over a minute to answer its first health probe there. Normal boots take ~3 s;
//   a healthy machine never feels this ceiling.
const HEALTH_TIMEOUT_MS = 120_000;
const KILL_GRACE_MS = 5_000;

/** The first free port at or after `start` — the desktop must not fight a dev server. */
function findFreePort(start) {
  return new Promise((resolve, reject) => {
    const probe = (port, attemptsLeft) => {
      if (attemptsLeft === 0) {
        reject(new Error(`no free port found near ${start}`));
        return;
      }
      const srv = net.createServer();
      srv.once('error', () => probe(port + 1, attemptsLeft - 1));
      srv.once('listening', () => srv.close(() => resolve(port)));
      srv.listen(port, '127.0.0.1');
    };
    probe(start, 50);
  });
}

/** Sidecar pidfile — how a boot recognises the previous session's leftovers. */
const PID_FILE_NAME = 'sidecars.lastpids';

/** Best-effort "is pid one of OUR sidecars" — guards stale-pid kills against reuse. */
function isSidecarProcess(pid) {
  try {
    if (process.platform === 'win32') {
      const out =
        spawnSync('tasklist', ['/FI', `PID eq ${pid}`], { encoding: 'utf8', windowsHide: true })
          .stdout || '';
      return out.toLowerCase().includes('python');
    }
    const cmd = fs.readFileSync(`/proc/${pid}/cmdline`, 'utf8');
    return cmd.includes('uvicorn') || cmd.includes('celery') || cmd.includes('app.serve');
  } catch {
    return false;
  }
}

/**
 * ★ Kill API/worker processes a PREVIOUS session left behind — same posture as the
 * leftover-postmaster and leftover-redis cleanups in runtime.js. A session that
 * dies without its stop() (SIGKILL, a crash — or, before the SIGINT handler in
 * main.js existed, a Ctrl+C in the launching terminal, which no longer reaches
 * the detached process groups) orphans celery/uvicorn; the orphan then latches
 * onto whatever NEW redis appears on its remembered port and spams reconnect
 * errors when that redis stops (field report). The pidfile names last session's
 * pids; any still alive AND still sidecar-shaped is ours to kill.
 */
function killStaleSidecars(pidFile, say) {
  let stale = [];
  try {
    stale = JSON.parse(fs.readFileSync(pidFile, 'utf8')).pids ?? [];
  } catch {
    return; // no pidfile — nothing to clean
  }
  let found = false;
  for (const pid of stale) {
    if (!Number.isInteger(pid) || pid <= 1 || !isSidecarProcess(pid)) continue;
    found = true;
    try {
      process.kill(-pid, 'SIGKILL'); // the whole leftover group, pool children included
    } catch {
      try {
        process.kill(pid, 'SIGKILL');
      } catch {
        /* already gone */
      }
    }
  }
  if (found) say('stopping leftover API/worker processes from a previous session…');
  fs.rmSync(pidFile, { force: true });
}

/** Run to completion; resolve on exit 0, reject with captured output otherwise. */
function runOnce(cmd, args, opts) {
  return new Promise((resolve, reject) => {
    // windowsHide: alembic would otherwise flash a cmd window on Windows.
    const child = spawn(cmd, args, { windowsHide: true, ...opts, stdio: ['ignore', 'pipe', 'pipe'] });
    let output = '';
    child.stdout.on('data', (d) => (output += d));
    child.stderr.on('data', (d) => (output += d));
    child.on('error', reject);
    child.on('exit', (code) =>
      code === 0
        ? resolve(output)
        : reject(new Error(`${path.basename(cmd)} ${args[1] ?? ''} exited ${code}:\n${output.slice(-2000)}`)),
    );
  });
}

function getJson(url) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { timeout: 3000 }, (res) => {
      let body = '';
      res.on('data', (d) => (body += d));
      res.on('end', () => resolve({ status: res.statusCode, body }));
    });
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.on('error', reject);
  });
}

async function waitForHealth(port, onStatus) {
  const deadline = Date.now() + HEALTH_TIMEOUT_MS;
  let lastError = 'not yet reachable';
  while (Date.now() < deadline) {
    try {
      const res = await getJson(`http://127.0.0.1:${port}/api/v1/health/ready`);
      if (res.status === 200) return;
      lastError = `health returned ${res.status}: ${res.body.slice(0, 300)}`;
    } catch (err) {
      lastError = String(err.message || err);
    }
    onStatus?.(`waiting for the API — ${lastError}`);
    await new Promise((r) => setTimeout(r, 700));
  }
  throw new Error(`The API never became healthy.\nLast error: ${lastError}`);
}

/**
 * Boot the whole family. Resolves to `{ port, url, stop }`; `stop()` is idempotent
 * and always safe to call (SIGTERM, then SIGKILL after a grace period).
 */
async function start({ onStatus, resources } = {}) {
  const say = (msg) => onStatus?.(msg);

  // ── MANAGED MODE: packaged app — bundled runtime + private postgres/redis ──
  const res = resources ?? resourcesDir();
  if (res) {
    const managed = await startManaged(res, say);
    // ★ gis/ai_engine ride as SOURCE beside the backend and PYTHONPATH puts them
    //   AHEAD of the runtime's site-packages — the runtime also carries pip-installed
    //   copies from whenever it was built, and a stale one once shipped an installer
    //   whose backend imported a gis symbol the baked gis did not have yet. Source
    //   shadows baked, so backend and gis can never version-skew again.
    const pythonPath = [
      managed.backendDir,
      path.join(res, 'gis-src'),
      path.join(res, 'ai_engine-src'),
    ].join(path.delimiter);
    return startProcesses({
      say,
      python: managed.python,
      backendDir: managed.backendDir,
      frontendDist: managed.frontendDist,
      apiCwd: managed.workDir,
      extraEnv: { ...managed.env, PYTHONPATH: pythonPath },
      stopServices: managed.stopServices,
    });
  }

  // ── DEV MODE: repo venv + system services, exactly as before ───────────────
  if (!fs.existsSync(PYTHON)) {
    throw new Error(
      `Python venv not found at ${PYTHON}.\nRun the backend setup first (see RUNNING.md), ` +
        'or point LE_DESKTOP_PYTHON at the right interpreter.',
    );
  }
  if (!fs.existsSync(path.join(FRONTEND_DIST, 'index.html'))) {
    throw new Error(
      `Built frontend not found at ${FRONTEND_DIST}.\nRun \`npm run build\` in frontend/ first.`,
    );
  }

  return startProcesses({
    say,
    python: PYTHON,
    backendDir: BACKEND,
    frontendDist: FRONTEND_DIST,
    apiCwd: BACKEND,
    extraEnv: {},
    stopServices: null,
  });
}

/**
 * The shared tail of both modes: migrations → API (+worker) → health → handle.
 * `apiCwd` is where the API RUNS (all its relative `./data/*` paths land there);
 * migrations always run from `backendDir`, where `alembic.ini` lives.
 */
async function startProcesses({ say, python, backendDir, frontendDist, apiCwd, extraEnv, stopServices }) {
  // ★ FIRST: reap what the previous session may have orphaned, before anything
  //   else binds ports or the new redis appears for an old worker to latch onto.
  const pidFile = path.join(apiCwd, PID_FILE_NAME);
  killStaleSidecars(pidFile, say);

  say('applying database migrations…');
  await runOnce(python, ['-m', 'alembic', 'upgrade', 'head'], {
    cwd: backendDir,
    env: { ...process.env, ...extraEnv },
  });

  const port = await findFreePort(Number(process.env.LE_DESKTOP_PORT || 8123));
  const children = [];
  const live = new Set();
  const track = (child) => {
    live.add(child);
    child.once('exit', () => live.delete(child));
    children.push(child);
    return child;
  };
  const env = { ...process.env, ...extraEnv, LE_SERVE_FRONTEND_DIR: frontendDist };

  // ★ POSIX: each sidecar leads its own PROCESS GROUP (`detached`), so stop() can
  //   signal the whole family with kill(-pid) — celery's prefork pool children die
  //   with their parent instead of surviving it. Windows has no process groups we
  //   can signal this way; taskkill /T in the escalation covers the tree there.
  const spawnOpts = {
    cwd: apiCwd,
    env,
    stdio: ['ignore', 'inherit', 'inherit'],
    // windowsHide: uvicorn/celery are console programs — each opened its own cmd
    // window on Windows otherwise. Ignored on POSIX.
    windowsHide: true,
  };
  if (process.platform !== 'win32') spawnOpts.detached = true;

  say(`starting the API on port ${port}…`);
  // ★ `app.serve`, not `-m uvicorn` directly: on Windows the selector event-loop
  //   policy must be set BEFORE uvicorn creates its loop, or async psycopg dies on
  //   the default Proactor loop at the first DB call (the 1.2.3 Windows failure).
  const api = track(
    spawn(
      python,
      ['-m', 'app.serve', '--host', '127.0.0.1', '--port', String(port)],
      spawnOpts,
    ),
  );

  if (process.env.LE_DESKTOP_WORKER !== '0') {
    say('starting the export worker…');
    const workerArgs = ['-m', 'celery', '-A', 'app.tasks.celery_app', 'worker', '--loglevel', 'warning',
      '-Q', 'cv,io,export,celery', '--concurrency', '2'];
    // ★ Celery's default prefork pool does not work on Windows (no fork). The
    //   threads pool does, and these queues are IO/export-shaped work.
    if (process.platform === 'win32') workerArgs.push('-P', 'threads');
    const worker = track(spawn(python, workerArgs, spawnOpts));
    // ★ A dead worker must not take the app down — exports degrade, uploads survive.
    worker.on('exit', (code) => {
      if (code !== 0 && code !== null) say(`worker exited (${code}) — exports are unavailable`);
    });
  }

  // ★ Record OUR pids so the NEXT boot can reap us if this session dies without
  //   its stop() (SIGKILL, crash). Removed again on every clean shutdown.
  try {
    fs.writeFileSync(pidFile, JSON.stringify({ pids: children.map((c) => c.pid) }));
  } catch {
    /* best effort — worst case the next boot has nothing to clean */
  }

  const alive = (child) => child.exitCode === null && child.signalCode === null;
  const signalChild = (child, sig) => {
    if (!alive(child)) return;
    try {
      // The negative pid addresses the whole process group on POSIX.
      if (process.platform !== 'win32') process.kill(-child.pid, sig);
      else child.kill(sig);
    } catch {
      try {
        child.kill(sig);
      } catch {
        /* already gone */
      }
    }
  };
  const forceKillChild = (child) => {
    if (!alive(child)) return;
    if (process.platform === 'win32') {
      // taskkill /T takes the whole tree down — Windows has no killable groups.
      spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], {
        stdio: 'ignore',
        windowsHide: true,
      });
    } else {
      try {
        process.kill(-child.pid, 'SIGKILL');
      } catch {
        try {
          child.kill('SIGKILL');
        } catch {
          /* already gone */
        }
      }
    }
  };

  let servicesStopped = false;
  const stopServicesOnce = () => {
    if (servicesStopped) return;
    servicesStopped = true;
    stopServices?.();
    // A clean shutdown leaves no pids for the next boot to worry about.
    fs.rmSync(pidFile, { force: true });
  };

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  /**
   * ★ AWAITED, NOT FIRE-AND-FORGET. The old implementation SIGTERMed the children
   * and scheduled both the SIGKILL escalation and the postgres/redis stop on an
   * `unref()`d timer — which died with the process the moment Electron finished
   * quitting. Every normal close therefore orphaned postgres + redis, and a busy
   * uvicorn/celery survived its SIGTERM indefinitely ("the laptop is slow even
   * after closing the app"). `main.js` now holds the quit until this resolves.
   */
  let stopPromise = null;
  const stop = () => {
    if (stopPromise) return stopPromise;
    stopPromise = (async () => {
      for (const child of children) signalChild(child, 'SIGTERM');
      const deadline = Date.now() + KILL_GRACE_MS;
      while (live.size > 0 && Date.now() < deadline) await sleep(150);
      if (live.size > 0) {
        for (const child of children) forceKillChild(child);
        const hardDeadline = Date.now() + 2_000;
        while (live.size > 0 && Date.now() < hardDeadline) await sleep(100);
      }
      // ★ Services LAST: the API needs postgres alive to shut down cleanly.
      //   stopServices is synchronous (pg_ctl stop blocks until the postmaster
      //   is down), so when this promise resolves, everything is truly gone.
      stopServicesOnce();
    })();
    return stopPromise;
  };

  /** Last-resort synchronous teardown for `process.on('exit')`, where nothing can
   *  be awaited: kill hard, then stop the services. Idempotent after `stop()`. */
  const stopSync = () => {
    for (const child of children) forceKillChild(child);
    try {
      stopServicesOnce();
    } catch {
      /* best effort */
    }
  };

  // The API dying on its own is fatal to the session — surface it, don't zombie.
  api.on('exit', (code) => {
    if (!stopPromise) say(`the API exited unexpectedly (${code})`);
  });

  try {
    await waitForHealth(port, onStatus_or(say));
  } catch (err) {
    await stop();
    throw err;
  }

  say('ready');
  return { port, url: `http://127.0.0.1:${port}/`, stop, stopSync };
}

/** waitForHealth expects the raw onStatus signature; adapt the local `say`. */
function onStatus_or(say) {
  return (msg) => say(msg);
}

module.exports = { start, findFreePort, FRONTEND_DIST, BACKEND, PYTHON };
