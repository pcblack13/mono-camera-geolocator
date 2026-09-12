"""The GEO1 wire format, as spoken by a Raspberry Pi sender.

Vendored rather than imported from ``tools/camera_stream`` for the reason every
other directory under ``app/vendor`` is: the backend must not reach outside its
own tree for something it depends on to start. The sender's copy stays the
reference implementation; this one is the app's, and the two are held together
by the format itself, which is versioned on the wire.
"""

from .protocol import MAGIC, VERSION, ProtocolError, read_message

__all__ = ["MAGIC", "VERSION", "ProtocolError", "read_message"]
