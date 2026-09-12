#!/usr/bin/env python3
"""
Wire format shared by the Pi sender and the PC app.

★ VENDORED COPY (2026-09-09). The sender at tools/camera_stream owns the
reference implementation; this is the app's own, so the backend has no
dependency on a path outside its tree. `VERSION` on the wire is what keeps
them honest: a sender speaking a version this does not know is refused by
name rather than misread.

Each message is  [data + frame + checksum]:

    magic     4 B   b"GEO1"
    version   1 B   currently 1
    hdr_len   4 B   uint32 big-endian
    img_len   4 B   uint32 big-endian
    header    hdr_len B   JSON, UTF-8  -- the detections and their geo fixes
    image     img_len B   JPEG, exactly as the camera produced it
    crc32     4 B   uint32 big-endian over header || image

The lengths are what make this work at all: TCP is a byte stream with no
message boundaries, so without them a reader cannot tell where one frame
ends and the next begins.

The CRC covers header and image together. A frame that fails it is dropped
rather than shown -- a corrupt JPEG usually still decodes into something,
and a plausible-looking picture with the wrong coordinates attached is worse
than a dropped frame.

Header schema (version 1):

    {
      "seq": 1234,                      # monotonic frame counter
      "ts": "2026-09-04T16:45:12.345678+00:00",   # UTC, ISO 8601
      "ts_unix": 1788528312.345678,
      "w": 1280, "h": 720,
      "source": "cogrpi5-desktop",
      "lut": "default_lut.npz",         # which table produced the fixes
      "objects_seq": 1233,              # frame the boxes were computed on; seq - objects_seq = lag
      "geo_valid": true,                # false once the drift guard says the camera moved
      "data_channel": "ethernet",       # "ethernet+uart" when the serial sink is on
      "uart": {"port": "/dev/ttyAMA10", "baud": 9600, "connected": true,
               "sent": 812, "dropped": 0, "reconnects": 0, "error": null},
      "pipeline": {"mode": "track", "detector_busy": false, "detector_ran": true,
                   "interrupt": false, "candidates": 0},
      "drift": {"valid": true, "status": "OK", "state": "OK", "rot_deg": 0.01,
                "alert_deg": 1.2, "landmarks": 12, "checks": 40, "error": null},
      "objects": [                      # ALWAYS here -- the serial line is a
                                        # parallel sink, never a replacement
        {
          "id": 7,                      # track id, stable while the track lives
          "cls": "person",
          "conf": 0.91,
          "bbox": [x1, y1, x2, y2],     # pixels, ints
          "anchor": [u, v],             # midpoint of the bottom edge
          "lat": 33.893791,             # null when the anchor has no ground fix
          "lon": 35.501871,
          "color": [r, g, b],           # stable per track id
          "state": "tracking",          # confirmed | tracking | refreshed | detected | lost
          "age": 42,                    # frames since the track was created
          "missed": 0                   # consecutive detector refreshes that did not confirm it
        }
      ]
    }
"""

import json
import socket
import struct
import zlib

MAGIC = b"GEO1"
VERSION = 1
HEADER_STRUCT = struct.Struct("!4sBII")     # magic, version, hdr_len, img_len
MAX_HEADER = 4 * 1024 * 1024
MAX_IMAGE = 32 * 1024 * 1024


class ProtocolError(Exception):
    """Malformed or corrupt message. The connection should be dropped."""


def pack(header, image):
    """Serialise one message. `header` is a dict, `image` raw JPEG bytes."""
    blob = json.dumps(header, separators=(",", ":")).encode("utf-8")
    crc = zlib.crc32(blob + image) & 0xFFFFFFFF
    return (HEADER_STRUCT.pack(MAGIC, VERSION, len(blob), len(image))
            + blob + image + struct.pack("!I", crc))


def recv_exactly(sock, n):
    """Read exactly n bytes. None if the peer closed before n arrived."""
    chunks = bytearray()
    while len(chunks) < n:
        chunk = sock.recv(n - len(chunks))
        if not chunk:
            return None
        chunks += chunk
    return bytes(chunks)


def read_message(sock):
    """Read one message. Returns (header dict, jpeg bytes), or None at EOF.

    Raises ProtocolError on a bad magic, an implausible length or a failed
    checksum -- all of which mean the stream is no longer trustworthy.
    """
    fixed = recv_exactly(sock, HEADER_STRUCT.size)
    if fixed is None:
        return None

    magic, version, hdr_len, img_len = HEADER_STRUCT.unpack(fixed)
    if magic != MAGIC:
        raise ProtocolError(f"bad magic {magic!r}, stream is out of sync")
    if version != VERSION:
        raise ProtocolError(f"unsupported version {version} (expected {VERSION})")
    # Bound the lengths before allocating: a corrupt header could otherwise
    # ask us to buffer gigabytes.
    if hdr_len > MAX_HEADER or img_len > MAX_IMAGE:
        raise ProtocolError(f"implausible lengths hdr={hdr_len} img={img_len}")

    body = recv_exactly(sock, hdr_len + img_len + 4)
    if body is None:
        return None

    blob, image, crc_bytes = (body[:hdr_len],
                              body[hdr_len:hdr_len + img_len],
                              body[hdr_len + img_len:])
    expected = struct.unpack("!I", crc_bytes)[0]
    actual = zlib.crc32(blob + image) & 0xFFFFFFFF
    if actual != expected:
        raise ProtocolError(f"checksum mismatch: got {actual:08x}, "
                            f"expected {expected:08x}")

    try:
        header = json.loads(blob.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProtocolError(f"header is not valid JSON: {exc}") from exc

    return header, image
