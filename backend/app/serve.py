"""Launch the API with an event loop async psycopg can actually use.

★ WHY THIS WRAPPER EXISTS: on Windows, Python's default asyncio loop is the
Proactor loop (since 3.8), and async psycopg refuses it outright —
``Psycopg cannot use the 'ProactorEventLoop' to run in async mode``. The desktop
shell used to start the API as ``python -m uvicorn app.main:app``, but uvicorn
creates its event loop BEFORE importing the app, so nothing inside ``app.*`` can
set the policy in time. The 1.2.3 Windows installer died at the migrations step
for exactly this error (alembic/env.py carries its own copy of the guard); had it
got past that, the API's first DB call would have failed the same way.

The fix is sequencing, not configuration: set the selector policy FIRST, then let
uvicorn build its loop under it. On POSIX this wrapper is a plain pass-through —
the desktop shell (boot.js) uses it on every platform so there is exactly one
launch path.

Usage:  python -m app.serve --host 127.0.0.1 --port 8123
"""

from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def main() -> None:
    """Parse the two flags the desktop shell passes and hand off to uvicorn."""
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Run the LandExplorer API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # ★ uvicorn.run creates the loop AFTER the policy set above — that ordering is
    #   the entire reason this module exists. No reload/workers here: the desktop
    #   runs exactly one API process and owns its lifecycle (boot.js).
    uvicorn.run("app.main:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
