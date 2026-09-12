"""``live_stream_service`` — the gate in front of a network grab.

★ These tests pin the REFUSALS and the naming, not the grab itself (that needs a
live camera and the test suite is offline by contract): a URL that is not
camera-shaped is refused by type with the fix named, and saved frames carry an
honest, sortable, filesystem-safe name.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.services.live_stream_service import (
    LiveCaptureError,
    _frame_filename,
    uncompressed_warning,
    validate_stream_url,
)


def _fourcc_int(code: str) -> int:
    """The integer OpenCV reports for a four-character format code."""
    return sum(ord(ch) << (8 * i) for i, ch in enumerate(code))


class _FakeCapture:
    """Just enough of ``cv2.VideoCapture`` for the format gate: `get` and `release`."""

    def __init__(self, fourcc: int) -> None:
        self._fourcc = fourcc
        self.released = False

    def get(self, _prop: int) -> float:
        return float(self._fourcc)

    def release(self) -> None:
        self.released = True


class TestValidateStreamUrl:
    def test_http_https_rtsp_pass(self) -> None:
        assert validate_stream_url("http://raspberrypi.local:8080/?action=stream")
        assert validate_stream_url("https://cam.example/snapshot.jpg")
        assert validate_stream_url("rtsp://192.168.1.50:554/stream1")

    @pytest.mark.parametrize(
        "url", ["file:///etc/passwd", "gopher://x", "ftp://cam/", "", "not a url", "//host/path"]
    )
    def test_non_camera_schemes_are_refused_by_type(self, url: str) -> None:
        # ★ SSRF posture: an attacker-shaped URL dies on the scheme check,
        #   before any socket is involved.
        with pytest.raises(LiveCaptureError, match="http://, https:// or rtsp://"):
            validate_stream_url(url)

    def test_a_scheme_with_no_host_is_refused(self) -> None:
        with pytest.raises(LiveCaptureError, match="no host"):
            validate_stream_url("http://")


class TestFrameFilename:
    NOW = datetime(2026, 8, 7, 12, 30, 45, tzinfo=UTC)

    def test_named_source(self) -> None:
        assert (
            _frame_filename("Pi Roof (north)!", "http://pi:8080/x", self.NOW)
            == "live_Pi_Roof_north_20260807_123045.jpg"
        )

    def test_unnamed_source_uses_the_host(self) -> None:
        assert (
            _frame_filename(None, "rtsp://192.168.1.50:554/s1", self.NOW)
            == "live_192_168_1_50_20260807_123045.jpg"
        )

    def test_never_an_empty_source_token(self) -> None:
        assert _frame_filename("///", "http://x/", self.NOW).startswith("live_")


class TestUncompressedWarning:
    """★ The MJPEG rule (1.2.6): ASK for MJPEG, WARN about raw, REFUSE nothing.

    An earlier build refused uncompressed devices outright and locked out a working
    greyscale camera. The lesson is in the docstring of `uncompressed_warning`: the
    thing that destroys frame rate is the DATA RATE, not the format — a small raw
    frame streams fine — and a slow picture is worth more to a surveyor than a
    refusal. So this reports; it never blocks.
    """

    def test_uncompressed_device_is_explained_not_refused(self) -> None:
        cap = _FakeCapture(_fourcc_int("YUYV"))
        note = uncompressed_warning(cap)
        assert note is not None
        # The warning must name the format and the consequence to watch for.
        assert "YUYV" in note
        assert "frames per second" in note
        # ★ THE POINT OF THE CHANGE: the device is left OPEN and usable.
        assert cap.released is False

    def test_greyscale_device_is_not_blocked(self) -> None:
        # The camera that the hard refusal broke: mono/IR sensors report GREY.
        cap = _FakeCapture(_fourcc_int("GREY"))
        assert uncompressed_warning(cap) is not None
        assert cap.released is False

    def test_warning_is_ascii_only(self) -> None:
        # ★ It travels as an HTTP header value; a stray em dash would break the
        #   response rather than merely look wrong.
        note = uncompressed_warning(_FakeCapture(_fourcc_int("YUYV")))
        assert note is not None
        note.encode("ascii")

    def test_mjpeg_device_has_nothing_to_say(self) -> None:
        assert uncompressed_warning(_FakeCapture(_fourcc_int("MJPG"))) is None

    def test_compressed_but_not_mjpeg_has_nothing_to_say(self) -> None:
        # An H264 capture card is compressed; frame rate is not the problem there.
        assert uncompressed_warning(_FakeCapture(_fourcc_int("H264"))) is None

    def test_unreadable_fourcc_is_not_treated_as_raw(self) -> None:
        # DirectShow commonly reports nothing. Unknown is not raw.
        assert uncompressed_warning(_FakeCapture(0)) is None
