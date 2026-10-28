import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from frameload.system import livestream as live  # noqa: E402


def box(kind, payload=b""):
    return struct.pack(">I4s", 8 + len(payload), kind.encode()) + payload


def full(kind, version, flags, payload=b""):
    return box(kind, bytes([version]) + flags.to_bytes(3, "big") + payload)


def moof(first_flags=None, track=1, default_flags=None):
    tf_flags = 0x20 if default_flags is not None else 0
    tfhd = full("tfhd", 0, tf_flags, struct.pack(">I", track) + (struct.pack(">I", default_flags)
                                                                 if default_flags is not None else b""))
    if first_flags is not None:
        trun = full("trun", 0, 0x4, struct.pack(">II", 1, first_flags))
    else:
        trun = full("trun", 0, 0, struct.pack(">I", 1))
    return box("moof", box("traf", tfhd + trun))


def init_segment():
    tkhd = full("tkhd", 0, 3, struct.pack(">III", 0, 0, 1) + b"\0" * 60)
    hdlr = full("hdlr", 0, 0, b"\0\0\0\0vide" + b"\0" * 12)
    trak = box("trak", tkhd + box("mdia", hdlr))
    avcc = b"avcC" + bytes([1, 0x64, 0x00, 0x28])
    return box("ftyp", b"isom") + box("moov", trak + box("stsd", avcc)), trak


class TestLiveStream(unittest.TestCase):
    def test_keyframes_and_codecs(self):
        init, _ = init_segment()
        self.assertEqual(live.video_track(init), 1)
        self.assertEqual(live.codecs(init), "avc1.640028")
        self.assertTrue(live.is_keyframe(moof(first_flags=0), 1))
        self.assertFalse(live.is_keyframe(moof(first_flags=live.SAMPLE_NON_SYNC), 1))
        self.assertTrue(live.is_keyframe(moof(default_flags=0), 1))
        self.assertFalse(live.is_keyframe(moof(first_flags=0, track=2), 1))  # the sound track says nothing

    def test_splitter_cuts_init_and_fragments_whatever_the_reads(self):
        init, _ = init_segment()
        frag = moof(first_flags=0) + box("mdat", b"x" * 50)
        stream = init + frag + frag
        out = []
        splitter = live.Splitter()
        for i in range(0, len(stream), 7):  # odd read sizes
            out += splitter.feed(stream[i:i + 7])
        self.assertEqual([k for k, _ in out], ["init", "fragment", "fragment"])
        self.assertEqual(out[0][1], init)
        self.assertEqual(out[1][1], frag)

    def test_the_script_uses_the_headset_view_and_the_outputs_monitor(self):
        text = live.script("/dev/video99", "720p", None)
        self.assertIn('-f v4l2 -input_format rgb24 -i "/dev/video99"', text)
        self.assertIn('"$sink.monitor"', text)
        self.assertIn("libx264", text)
        self.assertIn("nice -n 10", text)
        self.assertIn("frag_duration", text)


if __name__ == "__main__":
    unittest.main()
