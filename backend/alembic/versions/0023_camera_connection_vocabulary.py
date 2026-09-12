"""camera_connection_vocabulary

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-11

The connection vocabulary narrows to the three things that actually DIFFER
(owner decision 2026-09-11): an address on the network, a capture device on
this machine, a serial line.

    lan     ← lan, stream, embedded     an address (IP camera, Pi, any stream URL)
    usb     ← usb, hdmi, bnc            a capture device on this machine
    serial  ← serial, uart              a serial/UART line, data only

★ NO CAMERA CHANGES BEHAVIOUR. The eight old kinds asked for exactly three
things — an address, a device, or a port — and every fold above keeps the one
its rows were already using. ``stream`` and ``embedded`` cameras were opened by
the same code as ``lan`` (a URL handed to the capture), ``hdmi`` and ``bnc``
were ``device:N`` indices like ``usb``, and ``uart`` was read by the serial
reader. What is lost is a LABEL, not a capability, which is why the fold is
safe to do in one UPDATE.

★ THE DOWNGRADE CANNOT UNDO IT. Once ``bnc`` has become ``usb`` nothing records
that it was ever analogue, so the downgrade only restores the wide CHECK — the
rows stay folded. Stated here rather than discovered: a downgrade is a schema
retreat, not a time machine.
"""

from __future__ import annotations

from typing import Sequence

import geoalchemy2  # noqa: F401  # ★ see script.py.mako — never remove
import sqlalchemy as sa  # noqa: F401  # ★ same
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_CONNECTIONS = (
    "connection IN ('lan', 'stream', 'hdmi', 'usb', 'bnc', 'serial', 'uart', 'embedded')"
)
_NEW_CONNECTIONS = "connection IN ('lan', 'usb', 'serial')"
_OLD_SERIAL_IS_DATA = "connection NOT IN ('serial', 'uart') OR provides = 'data'"
_NEW_SERIAL_IS_DATA = "connection <> 'serial' OR provides = 'data'"


def upgrade() -> None:
    # The fold, before the narrower CHECK arrives — see the header for why each
    # of these keeps the behaviour its rows already had.
    op.execute("UPDATE cameras SET connection = 'lan' WHERE connection IN ('stream', 'embedded')")
    op.execute("UPDATE cameras SET connection = 'usb' WHERE connection IN ('hdmi', 'bnc')")
    op.execute("UPDATE cameras SET connection = 'serial' WHERE connection = 'uart'")
    op.drop_constraint("ck_cameras_serial_is_data", "cameras", type_="check")
    op.create_check_constraint("ck_cameras_serial_is_data", "cameras", _NEW_SERIAL_IS_DATA)
    op.drop_constraint("ck_cameras_connection_known", "cameras", type_="check")
    op.create_check_constraint("ck_cameras_connection_known", "cameras", _NEW_CONNECTIONS)


def downgrade() -> None:
    # Only the CHECKs widen again; the folded rows stay folded (see the header).
    op.drop_constraint("ck_cameras_connection_known", "cameras", type_="check")
    op.create_check_constraint("ck_cameras_connection_known", "cameras", _OLD_CONNECTIONS)
    op.drop_constraint("ck_cameras_serial_is_data", "cameras", type_="check")
    op.create_check_constraint("ck_cameras_serial_is_data", "cameras", _OLD_SERIAL_IS_DATA)
