import os
import struct
import sys
import unittest
import zlib
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from frameload.system import screenshot  # noqa: E402


def decode_png(data):
    """(width, height, rows) of an 8-bit RGB PNG made by screenshot.png."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, width = 8, b"", None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        assert struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])[0] == zlib.crc32(kind + body) & 0xFFFFFFFF
        if kind == b"IHDR":
            width, height = struct.unpack(">II", body[:8])
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = width * 3 + 1
    return width, height, [raw[i * stride + 1:(i + 1) * stride] for i in range(height)]


class TestScreenshot(unittest.TestCase):
    def test_png_holds_the_pixels(self):
        rows = [bytes([255, 0, 0, 0, 255, 0]), bytes([0, 0, 255, 9, 9, 9])]
        self.assertEqual(decode_png(screenshot.png(2, 2, rows)), (2, 2, rows))

    def test_a_frame_from_the_headset_view_skips_the_stale_ones(self):
        width, height = 4, 2
        stale = bytes([200]) * (width * 3 * height)
        frame = bytes(range(100, 100 + width * 3)) * height
        reads = [stale, stale, frame[:10], frame[10:]]
        with patch.object(screenshot.os, "open", return_value=3), patch.object(screenshot.os, "close"), \
                patch.object(screenshot, "_format", return_value=(width, height, width * 3, screenshot.BGR24)), \
                patch.object(screenshot.select, "select", return_value=([3], [], [])), \
                patch.object(screenshot.os, "read", side_effect=lambda fd, n: reads.pop(0)):
            data, black = screenshot._read_frame("/dev/video99", 1)
        w, h, rows = decode_png(data)
        self.assertEqual((w, h, black), (4, 2, False))
        self.assertEqual(rows[0][:3], bytes([102, 101, 100]))  # the third frame, BGR turned into RGB

    def test_a_black_picture_while_awake_restarts_the_headset_view_once(self):
        import tempfile, shutil
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        shots = [True, False]

        def capture(path, stamp, width):
            out = os.path.join(tmp, f"headset-{stamp}-{len(shots)}.jpg")
            open(out, "wb").write(b"jpeg")
            return {"path": out, "method": "ffmpeg", "black": shots.pop(0)}

        with patch.object(screenshot, "SCREENSHOT_DIR", tmp), patch.object(screenshot, "device", return_value="/dev/video99"), \
                patch.object(screenshot, "_capture", side_effect=capture), patch.object(screenshot, "RESTART_WAIT", 0), \
                patch.object(screenshot, "_restart_producer", return_value=True) as restart:
            shot = screenshot.take(1280, awake=True)
            self.assertEqual((shot["black"], shot["restarted"]), (False, True))
            restart.assert_called_once()
            shots[:] = [True]
            shot = screenshot.take(1280, awake=False)  # asleep: black is expected, nothing is restarted
            self.assertEqual((shot["black"], shot["restarted"]), (True, False))
            restart.assert_called_once()

    def test_no_picture_in_time_is_an_error(self):
        with patch.object(screenshot.os, "open", return_value=3), patch.object(screenshot.os, "close"), \
                patch.object(screenshot, "_format", return_value=(4, 2, 12, screenshot.RGB24)), \
                patch.object(screenshot.select, "select", return_value=([], [], [])), \
                patch.object(screenshot, "READ_TIMEOUT", 0.01):
            with self.assertRaises(screenshot.ScreenshotError):
                screenshot._read_frame("/dev/video99", 1)


if __name__ == "__main__":
    unittest.main()
