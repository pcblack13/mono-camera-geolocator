#!/usr/bin/env python3
"""Run the whole of LandExplorer — API, Celery worker, and frontend — from one terminal.

    python3 run.py                     # everything
    python3 run.py --only api,web      # skip the worker (no exports)
    python3 run.py --kill              # clear strays, then start
    python3 run.py --reload            # uvicorn autoreload for backend work
    python3 run.py --check             # run the preflight checks and exit

Ctrl+C once stops all three cleanly.

★ THIS SCRIPT USES THE STANDARD LIBRARY ONLY, and is run by the SYSTEM python3 — not by
the venv. It has to work *before* anything is installed, because diagnosing "nothing is
installed" is most of its job. It finds the venv itself and runs the backend with it.

★ THE THREE THINGS THAT ACTUALLY GO WRONG, all of which this script checks for by name:

1. **`ai_engine` and `gis` are not installed.** They are local path packages, not PyPI
   ones, so `pip install -r backend/requirements.txt` does not bring them and the API
   dies at import with ``ModuleNotFoundError: No module named 'ai_engine'``.

2. **The API and worker MUST start from `backend/`.** ``Settings`` declares
   ``env_file=".env"`` — a RELATIVE path, resolved against the current working directory.
   Started from the repo root, `backend/.env` is never read, every setting falls back to
   its default, and the defaults are the **docker-compose hostnames**: the worker dials
   ``redis:6379`` and the API dials ``db:5432``, neither of which resolves outside a
   container. It does not look like a config problem; it looks like Redis is down.

3. **A stale process holds the port.** ``--kill`` clears them.

★ Each service is started in its own process GROUP (``start_new_session=True``) so that
stopping means signalling the whole tree. ``npm run dev`` in particular spawns vite as a
child: signalling only npm leaves vite holding port 5173, and the next run fails with a
port conflict that has no visible owner.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"

API_HOST_DEFAULT = "127.0.0.1"
API_PORT_DEFAULT = 8000
WEB_PORT_DEFAULT = 5173

#: Queues the worker consumes. ``celery`` is the default queue and is included so that a
#: task routed nowhere in particular is still picked up rather than sitting invisibly.
QUEUES = "cv,io,export,celery"

#: Patterns identifying our own strays, for ``--kill``. Deliberately specific: a bare
#: ``pkill -f celery`` on a shared machine is somebody else's outage.
STRAY_PATTERNS = ("uvicorn app.main", "celery -A app.tasks", "vite")


# ── output ────────────────────────────────────────────────────────────────────

class C:
    """ANSI colours, blanked when the output is not a terminal (or NO_COLOR is set)."""

    enabled = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

    RESET = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
    RED = "\033[31m"; GREEN = "\033[32m"; YELLOW = "\033[33m"
    BLUE = "\033[34m"; MAGENTA = "\033[35m"; CYAN = "\033[36m"

    @classmethod
    def paint(cls, text: str, *codes: str) -> str:
        if not cls.enabled:
            return text
        return f"{''.join(codes)}{text}{cls.RESET}"


_print_lock = threading.Lock()


def say(message: str = "") -> None:
    """Print one line atomically — three log streams share this stdout.

    ★ **Never raises, and that is load-bearing.** Pipe this launcher into ``head`` (or
    into a ``tee`` you later close) and stdout breaks under us. If that surfaced as a
    ``BrokenPipeError`` it would unwind the supervisor mid-shutdown and leave the API,
    the worker and vite orphaned, still holding ports 8000 and 5173 — with no parent left
    to signal them. Losing a log line is a cosmetic problem; losing the ability to stop
    the stack is not.
    """
    try:
        with _print_lock:
            print(message, flush=True)
    except (BrokenPipeError, ValueError, OSError):
        pass


def ok(message: str) -> None:
    say(f"  {C.paint('✓', C.GREEN)} {message}")


def warn(message: str) -> None:
    say(f"  {C.paint('!', C.YELLOW)} {message}")


def fail(message: str) -> None:
    say(f"  {C.paint('✗', C.RED)} {message}")


def hint(message: str) -> None:
    say(f"    {C.paint(message, C.DIM)}")


def heading(message: str) -> None:
    say(f"\n{C.paint(message, C.BOLD)}")


# ── services ──────────────────────────────────────────────────────────────────

@dataclass
class Service:
    """One managed child process."""

    key: str
    label: str
    colour: str
    cmd: list[str]
    cwd: Path
    #: Printed once when the service is up, so a newcomer knows where to look.
    ready_note: str = ""
    process: subprocess.Popen[str] | None = field(default=None, repr=False)

    @property
    def tag(self) -> str:
        return C.paint(f"{self.label:<8}", self.colour, C.BOLD)


def build_services(args: argparse.Namespace, python: Path) -> list[Service]:
    """Assemble the service list from the CLI arguments."""
    api_cmd = [
        str(python), "-m", "uvicorn", "app.main:app",
        "--host", args.host, "--port", str(args.port),
    ]
    if args.reload:
        # ★ Watches SOURCE only. A `.env` edit still needs a manual restart — settings are
        #   read once at import, which is exactly how an API ends up running against a
        #   config file that was written after it booted.
        api_cmd += ["--reload", "--reload-dir", "app"]

    worker_cmd = [
        str(python), "-m", "celery", "-A", "app.tasks.celery_app", "worker",
        "--loglevel", args.loglevel, "-Q", QUEUES,
        "--concurrency", str(args.concurrency),
    ]

    npm = shutil.which("npm") or "npm"
    web_cmd = [npm, "run", "dev", "--", "--port", str(args.web_port), "--strictPort"]

    catalogue = {
        # ★ cwd=BACKEND for both: see this module's docstring, point 2.
        "api": Service(
            "api", "api", C.CYAN, api_cmd, BACKEND,
            ready_note=f"http://{args.host}:{args.port}/docs",
        ),
        "worker": Service(
            "worker", "worker", C.MAGENTA, worker_cmd, BACKEND,
            ready_note=f"queues: {QUEUES}",
        ),
        "web": Service(
            "web", "web", C.GREEN, web_cmd, FRONTEND,
            ready_note=f"http://localhost:{args.web_port}",
        ),
    }
    return [catalogue[k] for k in args.only if k in catalogue]


# ── preflight ─────────────────────────────────────────────────────────────────

def find_python() -> Path | None:
    """Locate the interpreter that has the backend's dependencies.

    Checks the usual venv locations in the order this project actually uses them. Returns
    None when none is found — an explicit failure beats silently falling back to the
    system python, which would produce a confusing ``ModuleNotFoundError: fastapi``.
    """
    for candidate in (
        BACKEND / "venv" / "bin" / "python",
        ROOT / ".venv" / "bin" / "python",
        ROOT / "venv" / "bin" / "python",
        BACKEND / ".venv" / "bin" / "python",
    ):
        if candidate.is_file():
            return candidate
    # Already inside an activated venv?
    if os.environ.get("VIRTUAL_ENV"):
        candidate = Path(os.environ["VIRTUAL_ENV"]) / "bin" / "python"
        if candidate.is_file():
            return candidate
    return None


def probe_backend(python: Path) -> dict[str, object]:
    """Ask the backend's own interpreter what it can see. Never raises.

    Runs inside the venv, with ``cwd=backend`` so that ``.env`` is loaded exactly as the
    real processes load it — the whole point is to report the settings that will actually
    be used, not the ones a different working directory would produce.
    """
    script = r"""
import json, importlib.util, sys
out = {}
for mod in ("ai_engine", "gis", "fastapi", "celery", "rasterio", "pyproj"):
    try:
        out[mod] = importlib.util.find_spec(mod) is not None
    except Exception:
        out[mod] = False
try:
    from app.core.config import Settings
    s = Settings()
    out["database_url"] = s.database_url
    out["redis_url"] = s.redis_url
    out["elevation_provider"] = str(s.elevation_provider)
    out["settings_ok"] = True
except Exception as exc:
    out["settings_ok"] = False
    out["settings_error"] = f"{type(exc).__name__}: {exc}"
print(json.dumps(out))
"""
    try:
        result = subprocess.run(
            [str(python), "-c", script],
            cwd=BACKEND, capture_output=True, text=True, timeout=90,
        )
        if result.returncode != 0:
            return {"probe_failed": result.stderr.strip()[-400:]}
        import json

        return json.loads(result.stdout.strip().splitlines()[-1])
    except Exception as exc:  # noqa: BLE001 - the probe must never take the launcher down
        return {"probe_failed": f"{type(exc).__name__}: {exc}"}


def check_tcp(url: str, default_port: int) -> tuple[bool, str]:
    """Open a TCP socket to whatever ``url`` points at. Returns ``(reachable, endpoint)``."""
    match = re.search(r"@?([A-Za-z0-9._-]+):(\d+)", url)
    host, port = (match.group(1), int(match.group(2))) if match else ("localhost", default_port)
    endpoint = f"{host}:{port}"
    try:
        with socket.create_connection((host, port), timeout=3):
            return (True, endpoint)
    except OSError:
        return (False, endpoint)


def port_owner(port: int) -> str | None:
    """Return a short description of whatever is listening on ``port``, if anything."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
            return None
        except OSError:
            pass
    try:
        out = subprocess.run(
            ["ss", "-ltnp", f"sport = :{port}"], capture_output=True, text=True, timeout=5
        ).stdout
        match = re.search(r'users:\(\("([^"]+)",pid=(\d+)', out)
        if match:
            return f"{match.group(1)} (pid {match.group(2)})"
    except Exception:  # noqa: BLE001 - ss may be absent; the port is still taken
        pass
    return "an unknown process"


def preflight(args: argparse.Namespace, python: Path | None) -> bool:
    """Check everything that has actually broken before. Returns False to stop the launch."""
    problems = 0

    heading("Environment")
    if python is None:
        fail("No virtualenv found.")
        hint("python3 -m venv backend/venv && backend/venv/bin/pip install -r requirements.txt")
        return False
    ok(f"python  {python.relative_to(ROOT) if python.is_relative_to(ROOT) else python}")

    if "web" in args.only:
        if not FRONTEND.is_dir():
            fail(f"No frontend directory at {FRONTEND}")
            problems += 1
        elif not (FRONTEND / "node_modules").is_dir():
            fail("frontend/node_modules is missing — `npm run dev` will fail with 'vite: not found'.")
            hint("cd frontend && npm ci")
            problems += 1
        else:
            ok("frontend dependencies installed")

    needs_backend = bool({"api", "worker"} & set(args.only))
    if not needs_backend:
        return problems == 0

    # ── the backend's own view of itself ──────────────────────────────────────
    heading("Backend")
    probe = probe_backend(python)
    if "probe_failed" in probe:
        fail("Could not inspect the backend environment:")
        hint(str(probe["probe_failed"]))
        return False

    missing = [m for m in ("ai_engine", "gis") if probe.get(m) is False]
    if missing:
        fail(f"Local path package(s) not installed: {', '.join(missing)}")
        hint("These are NOT on PyPI — requirements.txt does not bring them:")
        for m in missing:
            hint(f"  {python} -m pip install -e ./{m} --no-deps")
        problems += 1
    else:
        ok("ai_engine and gis installed")

    if probe.get("fastapi") is False:
        fail("fastapi is not installed in this venv.")
        hint(f"{python} -m pip install -r backend/requirements.txt")
        problems += 1

    if not (BACKEND / ".env").is_file():
        warn("backend/.env is missing — settings fall back to the docker-compose hostnames")
        hint("The worker will try redis:6379 and the API db:5432, and neither resolves here.")
        hint("Create backend/.env with LE_DATABASE_URL / LE_REDIS_URL / LE_SECRET_KEY.")

    if not probe.get("settings_ok"):
        fail(f"Settings could not be loaded: {probe.get('settings_error')}")
        return False

    # ── the services those settings point at ──────────────────────────────────
    heading("Services")
    db_url = str(probe.get("database_url", ""))
    redis_url = str(probe.get("redis_url", ""))

    reachable, endpoint = check_tcp(db_url, 5432)
    if reachable:
        ok(f"postgres  {endpoint}")
    else:
        fail(f"postgres unreachable at {endpoint}")
        if endpoint.startswith("db:"):
            hint("`db` is the docker-compose hostname — backend/.env is not being read.")
            hint("Both the API and the worker must start from backend/ (this script does).")
        else:
            hint("sudo systemctl start postgresql")
        problems += 1

    reachable, endpoint = check_tcp(redis_url, 6379)
    if reachable:
        ok(f"redis     {endpoint}")
    else:
        fail(f"redis unreachable at {endpoint}")
        if endpoint.startswith("redis:"):
            hint("`redis` is the docker-compose hostname — backend/.env is not being read.")
        else:
            hint("sudo systemctl start redis-server")
        problems += 1

    provider = probe.get("elevation_provider")
    if provider and provider != "none":
        ok(f"elevation {provider}")

    # ── ports ─────────────────────────────────────────────────────────────────
    heading("Ports")
    wanted = []
    if "api" in args.only:
        wanted.append((args.port, "api"))
    if "web" in args.only:
        wanted.append((args.web_port, "web"))
    for port, who in wanted:
        owner = port_owner(port)
        if owner is None:
            ok(f"{port:<5} free ({who})")
        else:
            fail(f"{port} is already held by {owner}")
            hint("Stop it, or re-run with --kill to clear our own strays.")
            problems += 1

    return problems == 0


def kill_strays() -> None:
    """Terminate leftover processes from a previous run.

    ``pkill`` exits 1 when nothing matched, which is the normal case and not an error —
    ``notes.txt`` makes the same point.
    """
    heading("Clearing strays")
    for pattern in STRAY_PATTERNS:
        result = subprocess.run(["pkill", "-f", pattern], capture_output=True)
        if result.returncode == 0:
            ok(f"stopped processes matching {pattern!r}")
        else:
            say(f"  {C.paint('·', C.DIM)} nothing matching {pattern!r}")
    time.sleep(1.0)  # let the ports actually be released before we bind them


# ── running ───────────────────────────────────────────────────────────────────

def pump(service: Service) -> None:
    """Stream one child's output, line by line, with its own coloured tag."""
    assert service.process is not None and service.process.stdout is not None
    for line in service.process.stdout:
        say(f"{service.tag} {C.paint('│', C.DIM)} {line.rstrip()}")


def start(service: Service, env: dict[str, str]) -> None:
    """Launch one service in its own process group."""
    service.process = subprocess.Popen(
        service.cmd,
        cwd=service.cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        # ★ Its own session, so signalling the group reaches grandchildren — npm's vite
        #   child above all. Without it, vite survives and keeps port 5173.
        start_new_session=True,
    )
    threading.Thread(target=pump, args=(service,), daemon=True).start()


def _signal_group(service: Service, sig: int) -> None:
    """Send ``sig`` to a service's whole process group. Never raises."""
    if service.process is None:
        return
    try:
        os.killpg(os.getpgid(service.process.pid), sig)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def stop_all(services: list[Service], grace: float = 8.0) -> None:
    """Stop every child: SIGINT to the group, then SIGKILL to whatever is left.

    ★ **Signalling happens FIRST, before any output.** Reporting is a courtesy; stopping
    is the contract. Interleaving them means an stdout failure part-way through the report
    strands whichever children had not been signalled yet.
    """
    live = [s for s in services if s.process and s.process.poll() is None]
    if not live:
        return

    for service in live:
        _signal_group(service, signal.SIGINT)

    say("")
    heading("Stopping")

    deadline = time.time() + grace
    while time.time() < deadline:
        if all(s.process is None or s.process.poll() is not None for s in live):
            break
        time.sleep(0.2)

    for service in live:
        assert service.process is not None
        if service.process.poll() is None:
            _signal_group(service, signal.SIGKILL)
            warn(f"{service.label} ignored SIGINT after {grace:.0f}s — killed")
        else:
            ok(f"{service.label} stopped")

    # ★ Last resort. `poll()` reports the process we spawned, not its descendants: npm
    #   can exit while the vite it forked lives on, and a surviving vite keeps port 5173
    #   with no visible owner. Signalling the group again after the fact costs nothing
    #   when it is already empty.
    for service in live:
        _signal_group(service, signal.SIGKILL)


def run(services: list[Service], args: argparse.Namespace) -> int:
    """Start everything and supervise until Ctrl+C or a child dies."""
    env = os.environ.copy()
    # Unbuffered children, so their logs interleave in real time instead of arriving in
    # 4 KB bursts that make the ordering meaningless.
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("FORCE_COLOR", "1")

    heading("Starting")
    for service in services:
        start(service, env)
        where = service.cwd.relative_to(ROOT) if service.cwd.is_relative_to(ROOT) else service.cwd
        ok(f"{service.label:<7} pid {service.process.pid:<7} cwd {where}")

    say("")
    say(C.paint("  ─" * 30, C.DIM))
    for service in services:
        if service.ready_note:
            say(f"  {service.tag} {service.ready_note}")
    say(f"  {C.paint('Ctrl+C to stop everything', C.DIM)}")
    say(C.paint("  ─" * 30, C.DIM))
    say("")

    stopping = False

    def on_signal(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    exit_code = 0
    try:
        while not stopping:
            for service in services:
                assert service.process is not None
                code = service.process.poll()
                if code is not None:
                    # ★ Fail fast and loud. A dead worker with a live API is the state
                    #   where uploads succeed and exports hang forever with no error —
                    #   the failure a surveyor discovers at the end of the job.
                    say("")
                    if code < 0:
                        # Popen reports a signal death as a NEGATIVE code. Say which
                        #   signal, and exit 128+N as a shell expects — a raw -9 becomes
                        #   247 through sys.exit and means nothing to anyone.
                        signame = signal.Signals(-code).name
                        fail(f"{service.label} was killed by {signame} — stopping the rest.")
                        exit_code = 128 - code
                    else:
                        fail(f"{service.label} exited with code {code} — stopping the rest.")
                        exit_code = code or 1
                    if service.key == "api" and code == 1:
                        hint("Scroll up for the traceback; a missing ai_engine/gis import")
                        hint("or an unreadable backend/.env are the usual causes.")
                    stopping = True
                    break
            time.sleep(0.3)
    finally:
        stop_all(services)

    return exit_code


# ── cli ───────────────────────────────────────────────────────────────────────

def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="Run LandExplorer's API, Celery worker and frontend together.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python3 run.py                  everything\n"
            "  python3 run.py --only api,web   no worker (exports will not run)\n"
            "  python3 run.py --kill --reload  clear strays, autoreload the API\n"
            "  python3 run.py --check          preflight only, then exit\n"
        ),
    )
    parser.add_argument(
        "--only", default="api,worker,web",
        help="Comma-separated subset of api,worker,web (default: all three).",
    )
    parser.add_argument("--host", default=API_HOST_DEFAULT, help="API bind host.")
    parser.add_argument("--port", type=int, default=API_PORT_DEFAULT, help="API port.")
    parser.add_argument("--web-port", type=int, default=WEB_PORT_DEFAULT, help="Vite port.")
    parser.add_argument("--concurrency", type=int, default=2, help="Celery worker processes.")
    parser.add_argument("--loglevel", default="info", help="Celery log level.")
    parser.add_argument("--reload", action="store_true", help="Autoreload the API on source edits.")
    parser.add_argument("--kill", action="store_true", help="Clear stray processes before starting.")
    parser.add_argument("--check", action="store_true", help="Run the preflight checks and exit.")
    parser.add_argument("--skip-checks", action="store_true", help="Start without preflight checks.")
    parser.add_argument("--no-color", action="store_true", help="Disable coloured output.")

    args = parser.parse_args(argv)
    if args.no_color:
        C.enabled = False

    chosen = [part.strip() for part in args.only.split(",") if part.strip()]
    unknown = [part for part in chosen if part not in ("api", "worker", "web")]
    if unknown:
        parser.error(f"unknown service(s): {', '.join(unknown)}. Choose from api, worker, web.")
    if not chosen:
        parser.error("--only selected no services")
    args.only = chosen
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    say(C.paint("\nLandExplorer", C.BOLD) + C.paint("  — manual GCP surveying tool", C.DIM))
    say(C.paint(f"  {ROOT}", C.DIM))

    if args.kill:
        kill_strays()

    python = find_python()
    if not args.skip_checks:
        if not preflight(args, python):
            say("")
            fail("Preflight failed — fix the above, or re-run with --skip-checks to start anyway.")
            return 1
        if args.check:
            say("")
            ok("All checks passed.")
            return 0
    elif args.check:
        warn("--check with --skip-checks does nothing.")
        return 0

    if python is None:
        fail("No virtualenv found and checks were skipped; cannot start the backend.")
        return 1

    services = build_services(args, python)
    return run(services, args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        # Ctrl+C during preflight, before the supervisor installs its own handler.
        say("\nInterrupted.")
        sys.exit(130)
