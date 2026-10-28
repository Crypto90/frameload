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

    def test_a_frame_from_the_headset_view(self):
        width, height = 4, 2
        frame = bytes(range(width * 3)) * height
        reads = [frame[:10], frame[10:]]
        with patch.object(screenshot.os, "open", return_value=3), patch.object(screenshot.os, "close"), \
                patch.object(screenshot, "_format", return_value=(width, height, width * 3, screenshot.BGR24)), \
                patch.object(screenshot.select, "select", return_value=([3], [], [])), \
                patch.object(screenshot.os, "read", side_effect=lambda fd, n: reads.pop(0)):
            w, h, rows = decode_png(screenshot._read_frame("/dev/video99", 1))
        self.assertEqual((w, h), (4, 2))
        self.assertEqual(rows[0][:3], bytes([2, 1, 0]))  # BGR turned into RGB

    def test_no_picture_in_time_is_an_error(self):
        with patch.object(screenshot.os, "open", return_value=3), patch.object(screenshot.os, "close"), \
                patch.object(screenshot, "_format", return_value=(4, 2, 12, screenshot.RGB24)), \
                patch.object(screenshot.select, "select", return_value=([], [], [])), \
                patch.object(screenshot, "READ_TIMEOUT", 0.01):
            with self.assertRaises(screenshot.ScreenshotError):
                screenshot._read_frame("/dev/video99", 1)


if __name__ == "__main__":
    unittest.main()
