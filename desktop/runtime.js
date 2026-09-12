/**
 * `desktop/runtime.js` — the MANAGED runtime: bundled Python + PostgreSQL/PostGIS +
 * Redis, provisioned on first launch, owned entirely by the app.
 *
 * ★ TWO MODES, decided by whether a resources directory exists (`app.isPackaged` →
 *   Electron's resourcesPath; `LE_DESKTOP_RESOURCES` for headless tests):
 *   - DEV: no resources → `boot.js` uses the repo venv and the system services,
 *     exactly as before. Nothing here runs.
 *   - MANAGED: resources present → everything below happens: unpack the conda-pack
 *     runtime into app-data on first run (`conda-unpack` rewrites its prefixes),
 *     `initdb` a private PostgreSQL cluster, start postgres + redis on free ports,
 *     create the database, and hand `boot.js` the interpreter + env to run the
 *     API/worker against THIS stack. The user's machine needs nothing installed.
 *
 * ★ The cluster is app-private and local-only: `listen_addresses=127.0.0.1`, trust
 *   auth, a random free port, data under the app-data dir. That is the standard
 *   embedded-database posture (what every "embedded postgres" library does) — the
 *   surface is a loopback port on a single-user machine, holding that user's own
 *   survey data.
 */

'use strict';

const { spawn, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

/** Where the immutable payload lives (AppImage/deb resources), or null in dev. */
function resourcesDir() {
  const fromEnv = process.env.LE_DESKTOP_RESOURCES;
  if (fromEnv) return path.resolve(fromEnv);
  return null; // main.js passes Electron's process.resourcesPath explicitly
}

function appDataDir() {
  if (process.env.LE_DESKTOP_APPDATA) return path.resolve(process.env.LE_DESKTOP_APPDATA);
  // Windows: %LOCALAPPDATA% is the platform's ~/.local/share (roaming profiles
  // must not sync a multi-GB runtime + database).
  const xdg =
    process.platform === 'win32'
      ? process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local')
      : process.env.XDG_DATA_HOME || path.join(os.homedir(), '.local', 'share');
  const dir = path.join(xdg, 'MonoCameraGeolocator');
  // ★ THE RENAME MIGRATION. Installs from the LandExplorer era keep their whole
  //   world (pgdata, runtime, uploads) under the old folder; a same-filesystem
  //   rename is atomic and instant, so the first launch after upgrading simply
  //   carries everything across. Only when the new home does not exist yet —
  //   a fresh install next to an old folder must never steal it.
  const legacy = path.join(xdg, 'LandExplorer');
  if (!fs.existsSync(dir) && fs.existsSync(legacy)) {
    try {
      fs.renameSync(legacy, dir);
    } catch {
      return legacy; // cross-device or locked: keep using the old home rather than split data
    }
  }
  return dir;
}

/**
 * Run a command to completion WITHOUT blocking the event loop; resolve stdout.
 *
 * ★ WHY ASYNC IS LOAD-BEARING HERE, not style: this module runs in Electron's
 *   MAIN process, and the first-run provisioning (tar unpack ~1 min, conda-unpack,
 *   initdb) used spawnSync — the window could not process a single event for the
 *   whole stretch, so GNOME declared the app "not responding" and offered Force
 *   Quit on EVERY first launch (field report). The child processes do exactly the
 *   same work; only the waiting is now non-blocking, so the splash keeps
 *   animating and the desktop stays convinced the app is alive.
 */
function runAsync(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    // windowsHide: console subprocesses (initdb, psql, tar…) otherwise flash a
    // cmd window each on Windows. Ignored on POSIX.
    const child = spawn(cmd, args, { windowsHide: true, ...opts, stdio: ['ignore', 'pipe', 'pipe'] });
    let output = '';
    child.stdout.on('data', (d) => (output += d));
    child.stderr.on('data', (d) => (output += d));
    child.on('error', reject);
    child.on('exit', (code) =>
      code === 0
        ? resolve(output)
        : reject(
            new Error(`${path.basename(cmd)} ${args.join(' ')} exited ${code}:\n${output.slice(-1500)}`),
          ),
    );
  });
}

/** Spawn, wait, resolve the exit status — never rejects. For probes and best-effort stops. */
function spawnStatus(cmd, args) {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, { windowsHide: true, stdio: 'ignore' });
    child.on('error', () => resolve(-1));
    child.on('exit', (code) => resolve(code ?? -1));
  });
}

/** Recursive delete that outlasts an orphaned writer (5 tries, 2s apart). */
async function rmrf(dir) {
  for (let attempt = 1; ; attempt += 1) {
    try {
      fs.rmSync(dir, { recursive: true, force: true });
      return;
    } catch (err) {
      if (attempt >= 5) throw err;
      // Non-blocking pause — the splash must keep painting while we outwait the orphan.
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
  }
}

/** First-run: untar the conda-pack runtime and fix its prefixes in place. */
async function ensureRuntime(resources, appData, say) {
  const runtimeDir = path.join(appData, 'runtime');
  const okMarker = path.join(runtimeDir, '.unpacked-ok');
  const tarball = path.join(resources, 'runtime.tar.gz');
  // ★ THE MARKER RECORDS WHERE the unpack happened AND WHICH RUNTIME it was,
  //   and any mismatch voids it.
  //   WHERE: conda-unpack bakes ABSOLUTE paths into the env at relocation time,
  //   so a runtime that has MOVED (the LandExplorer→MonoCameraGeolocator
  //   data-folder migration, a copied home directory, a changed XDG_DATA_HOME)
  //   is broken at its new address — postgres greets it with "moved away from
  //   its proper location" and the boot hangs.
  //   WHICH: an installer UPGRADE ships a new tarball, but the old unpacked
  //   runtime still sits in app-data — a 1.1.x machine kept booting the July
  //   hollow runtime (no numpy) long after the fixed .deb was installed,
  //   because existence was the only check. Version + tarball size in the
  //   stamp make every upgrade refresh the runtime.
  //   Wiping and re-unpacking (~a minute) is the only honest repair, and the
  //   runtime is disposable by design: pgdata and uploads live OUTSIDE it and
  //   are never touched. Legacy markers without the full stamp are treated as
  //   stale — one extra re-unpack, in exchange for never trusting a stale env.
  const stamp = `${runtimeDir}|v${require('./package.json').version}|${
    fs.existsSync(tarball) ? fs.statSync(tarball).size : 0
  }`;
  if (fs.existsSync(okMarker)) {
    if (fs.readFileSync(okMarker, 'utf8').trim() === stamp) return runtimeDir;
    say('new app version — refreshing the bundled runtime…');
  }

  const prebuilt = path.join(resources, 'runtime');
  const tmpDir = `${runtimeDir}.unpacking`;
  // ★ rm WITH RETRIES. If a previous boot was SIGKILLed (OOM) mid-unpack, its
  //   tar CHILD survives the parent and keeps extracting into the old dir for a
  //   while — a single rmSync then races live writes and dies with ENOTEMPTY
  //   (seen in the field on 1.2.0). Retrying with a pause outlasts the orphan.
  await rmrf(tmpDir);
  await rmrf(runtimeDir);
  fs.mkdirSync(appData, { recursive: true }); // parent for the rename/symlink below

  if (fs.existsSync(tarball)) {
    say('first run — unpacking the bundled runtime (a few hundred MB, once)…');
    // ★ `tar` exists on BOTH platforms: GNU tar on Linux, bsdtar (System32) on
    //   Windows 10 1803+ — the app's Windows floor.
    // ★ ATOMIC: extract into a sibling temp dir, then a single rename puts the
    //   complete tree at the live path. A kill at ANY point leaves either
    //   nothing at runtimeDir or a complete tree without a marker — both of
    //   which the next boot repairs. A half-written tree at the live path is
    //   no longer a reachable state.
    fs.mkdirSync(tmpDir, { recursive: true });
    await runAsync('tar', ['-xzf', tarball, '-C', tmpDir]);
    fs.renameSync(tmpDir, runtimeDir);
    // ★ conda-pack ships the fixer INSIDE the archive: it rewrites every prefix to
    //   wherever the env actually landed — which is why it runs AFTER the rename
    //   (run inside tmpDir, it would bake the temp path into the env).
    //   Linux: invoked THROUGH the bundled interpreter — the script's
    //   `#!/usr/bin/env python` shebang would otherwise demand a system python a
    //   blank machine does not have. Windows: conda-pack ships a real .exe.
    say('first run — relocating the runtime…');
    if (process.platform === 'win32') {
      await runAsync(path.join(runtimeDir, 'Scripts', 'conda-unpack.exe'), [], { cwd: runtimeDir });
    } else {
      await runAsync(
        path.join(runtimeDir, 'bin', 'python'),
        [path.join(runtimeDir, 'bin', 'conda-unpack')],
        { cwd: runtimeDir },
      );
    }
  } else if (fs.existsSync(prebuilt)) {
    // Test/dev convenience: a runtime directory used AT its build path needs no
    // unpacking — symlink through so smoke tests skip the slow tar round-trip.
    // ('junction' so Windows dev needs no admin rights; ignored on POSIX.)
    fs.rmSync(runtimeDir, { recursive: true, force: true });
    fs.symlinkSync(prebuilt, runtimeDir, 'junction');
    return runtimeDir;
  } else {
    throw new Error(`No runtime found in ${resources} (neither runtime.tar.gz nor runtime/).`);
  }
  fs.writeFileSync(okMarker, stamp);
  return runtimeDir;
}

/** Best-effort "is pid a redis-server of ours" — guards the pidfile cleanup
 *  against pid reuse. Linux reads /proc; Windows asks tasklist. */
function isRedisProcess(pid) {
  try {
    if (process.platform === 'win32') {
      const out =
        spawnSync('tasklist', ['/FI', `PID eq ${pid}`], { encoding: 'utf8', windowsHide: true })
          .stdout || '';
      return out.toLowerCase().includes('redis-server');
    }
    return fs.readFileSync(`/proc/${pid}/cmdline`, 'utf8').includes('redis-server');
  } catch {
    return false;
  }
}

async function findFreePort(start) {
  const net = require('node:net');
  return new Promise((resolve, reject) => {
    const probe = (port, left) => {
      if (left === 0) return reject(new Error(`no free port near ${start}`));
      const srv = net.createServer();
      srv.once('error', () => probe(port + 1, left - 1));
      srv.once('listening', () => srv.close(() => resolve(port)));
      srv.listen(port, '127.0.0.1');
    };
    probe(start, 50);
  });
}

function waitFor(check, what, timeoutMs = 30_000) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;
    const tick = async () => {
      let ok = false;
      try {
        ok = await check(); // sync or async checks both welcome
      } catch {
        ok = false;
      }
      if (ok) return resolve(undefined);
      if (Date.now() > deadline) return reject(new Error(`${what} did not come up in time`));
      setTimeout(tick, 400);
    };
    void tick();
  });
}

/**
 * Provision + start the managed services. Returns
 * `{ python, env, backendDir, frontendDist, stopServices }` for `boot.js`.
 */
async function startManaged(resources, say) {
  const appData = appDataDir();
  fs.mkdirSync(appData, { recursive: true });
  const runtime = await ensureRuntime(resources, appData, say);
  const win = process.platform === 'win32';
  // ★ CONDA LAYOUTS DIFFER BY OS, and this is the one place that knows it:
  //   - Linux env:   bin/python, bin/postgres, bin/redis-server
  //   - Windows env: python.exe at the env ROOT; postgres tools in Library\bin;
  //     and NO redis at all (conda-forge has no win-64 redis) — Windows ships a
  //     pinned community build in resources/redis-win instead (see package.json
  //     `win.extraResources` + runtime-build/build-runtime.ps1).
  const pyBin = () => (win ? path.join(runtime, 'python.exe') : path.join(runtime, 'bin', 'python'));
  // ★ Windows postgres lives in its OWN subtree (Library\pgsql), not Library\bin:
  //   EDB's binaries ship their own OpenSSL DLLs, and merging them into the
  //   conda Library once REPLACED python's libssl — pip lost the ssl module on
  //   the very build that created the runtime. Separate trees, no shared DLLs.
  const pgBin = (name) =>
    win
      ? path.join(runtime, 'Library', 'pgsql', 'bin', `${name}.exe`)
      : path.join(runtime, 'bin', name);
  const redisBin = () =>
    win
      ? path.join(resources, 'redis-win', 'redis-server.exe')
      : path.join(runtime, 'bin', 'redis-server');
  const bin = pgBin; // postgres tools are the only remaining `bin()` callers below

  // ── PostgreSQL ──────────────────────────────────────────────────────────────
  const pgData = path.join(appData, 'pgdata');
  if (!fs.existsSync(path.join(pgData, 'PG_VERSION'))) {
    say('first run — creating the database cluster…');
    await runAsync(bin('initdb'), ['-D', pgData, '-U', 'landexplorer', '-A', 'trust', '-E', 'UTF8', '--no-locale']);
  }
  // ★ A previous session that crashed (or was SIGKILLed) leaves its postmaster
  //   alive and holding both the data-dir lock and its port. This cluster is OURS
  //   exclusively — stop any survivor before starting fresh, or the new postmaster
  //   refuses to boot with "lock file postmaster.pid already exists".
  if (fs.existsSync(path.join(pgData, 'postmaster.pid'))) {
    say('stopping a leftover database from a previous session…');
    // Best-effort, up to 20 s — awaited, so a slow stop never freezes the window.
    await spawnStatus(bin('pg_ctl'), ['-D', pgData, 'stop', '-m', 'fast', '-t', '20']);
    fs.rmSync(path.join(pgData, 'postmaster.pid'), { force: true });
  }

  const pgPort = await findFreePort(15432);
  // ★ Sockets live in a SHORT /tmp dir, never under app-data: postgres hard-caps
  //   the socket path at 107 bytes, and a deep home (or test scratch) directory
  //   silently kills the whole cluster start. Sockets are transient; /tmp is right.
  //   Literal '/tmp' — os.tmpdir() honours $TMPDIR, which can itself be deep.
  //   Windows has no Unix sockets at all: TCP on loopback is the whole story there.
  const pgArgs = ['-D', pgData, '-p', String(pgPort), '-c', 'listen_addresses=127.0.0.1'];
  if (!win) {
    const sockets = fs.mkdtempSync('/tmp/le-pg-');
    pgArgs.push('-k', sockets);
  }
  say(`starting PostgreSQL on 127.0.0.1:${pgPort}…`);
  // ★ windowsHide on the long-lived services too — without it, postgres and redis
  //   each kept a visible cmd window open for the app's whole lifetime on Windows.
  // ★ detached on POSIX, for the same reason boot.js detaches the API/worker: a
  //   service left in the TERMINAL'S foreground process group receives the
  //   terminal's Ctrl+C DIRECTLY and dies instantly — redis and postgres went down
  //   BEFORE the worker was stopped, inverting the teardown order and stranding
  //   celery in its broker-reconnect loop (field report). In their own groups they
  //   stop only when stopServices says so, AFTER the children are gone. Windows is
  //   untouched (no signalable groups there; taskkill/pg_ctl already cover it).
  const serviceSpawnOpts = {
    stdio: ['ignore', 'inherit', 'inherit'],
    windowsHide: true,
  };
  if (!win) serviceSpawnOpts.detached = true;
  const postgres = spawn(bin('postgres'), pgArgs, serviceSpawnOpts);
  try {
    // ★ -U landexplorer: without it pg_isready probes as the OS user, and every
    //   boot log gained a scary-but-harmless `FATAL: role "pc" does not exist`.
    // ★ 90 s, not the default 30: a FIRST Windows boot starts postgres while
    //   Defender is still scanning the thousands of files the runtime unpack just
    //   wrote — 30 s tripped on slow disks. Normal boots pass in ~1 s regardless.
    await waitFor(
      async () =>
        (await spawnStatus(bin('pg_isready'), [
          '-h', '127.0.0.1', '-p', String(pgPort), '-U', 'landexplorer', '-d', 'postgres',
        ])) === 0,
      'PostgreSQL',
      90_000,
    );
  } catch (err) {
    // ★ Never leak a half-started postmaster: it would block every later launch.
    if (postgres.exitCode === null) postgres.kill('SIGTERM');
    throw err;
  }
  const dbExists =
    (await runAsync(bin('psql'), ['-h', '127.0.0.1', '-p', String(pgPort), '-U', 'landexplorer', '-d', 'postgres', '-tAc',
      "SELECT 1 FROM pg_database WHERE datname='landexplorer'"])).trim() === '1';
  if (!dbExists) {
    say('first run — creating the database…');
    await runAsync(bin('createdb'), ['-h', '127.0.0.1', '-p', String(pgPort), '-U', 'landexplorer', 'landexplorer']);
  }

  // ── Redis ───────────────────────────────────────────────────────────────────
  const redisPort = await findFreePort(16379);
  const redisDir = path.join(appData, 'redis');
  fs.mkdirSync(redisDir, { recursive: true });
  // ★ Like the postmaster.pid check above, but for redis: a session that was
  //   SIGKILLed — or any pre-fix build, which never stopped its services at all —
  //   leaves redis-server running forever, and unlike postgres they ACCUMULATE
  //   (each boot picks a fresh port, so nothing collides and nothing cleans up).
  //   We record our redis pid; a recorded pid still alive at the next boot is
  //   OURS and is stopped before a new one starts. The /proc (or tasklist) name
  //   check guards against pid reuse killing an innocent process.
  const redisPidFile = path.join(redisDir, 'redis.lastpid');
  if (fs.existsSync(redisPidFile)) {
    const stale = Number(fs.readFileSync(redisPidFile, 'utf8').trim());
    if (Number.isInteger(stale) && stale > 1 && isRedisProcess(stale)) {
      say('stopping a leftover redis from a previous session…');
      try {
        process.kill(stale, 'SIGTERM');
      } catch {
        /* already gone */
      }
    }
    fs.rmSync(redisPidFile, { force: true });
  }
  say(`starting Redis on 127.0.0.1:${redisPort}…`);
  // ★ Same detachment as postgres above — the terminal's Ctrl+C must not reach it.
  const redisSpawnOpts = { stdio: ['ignore', 'ignore', 'inherit'], windowsHide: true };
  if (!win) redisSpawnOpts.detached = true;
  const redis = spawn(
    redisBin(),
    ['--port', String(redisPort), '--bind', '127.0.0.1', '--dir', redisDir, '--save', '', '--appendonly', 'no'],
    redisSpawnOpts,
  );
  try {
    fs.writeFileSync(redisPidFile, String(redis.pid));
  } catch {
    /* best effort — worst case the next boot has nothing to clean */
  }

  // ── the writable working directory (all ./data/* paths land here) ───────────
  const workDir = path.join(appData, 'work');
  fs.mkdirSync(path.join(workDir, 'data'), { recursive: true });

  const stopServices = () => {
    // API/worker are already down (boot.js stops them first). Fast, ordered stop.
    if (redis.exitCode === null) redis.kill('SIGTERM');
    if (postgres.exitCode === null) {
      const res = spawnSync(bin('pg_ctl'), ['-D', pgData, 'stop', '-m', 'fast', '-t', '20'], {
        windowsHide: true,
      });
      if (res.status !== 0 && postgres.exitCode === null) postgres.kill('SIGTERM');
    }
  };

  return {
    python: pyBin(),
    backendDir: path.join(resources, 'backend'),
    frontendDist: path.join(resources, 'frontend-dist'),
    workDir,
    env: {
      LE_DATABASE_URL: `postgresql+psycopg://landexplorer@127.0.0.1:${pgPort}/landexplorer`,
      LE_REDIS_URL: `redis://127.0.0.1:${redisPort}/0`,
    },
    stopServices,
  };
}

module.exports = { resourcesDir, appDataDir, startManaged };
