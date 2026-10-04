"""Tests for binary VDF encoding and decoding."""
from __future__ import annotations

import unittest
from frameload.system.steam_vdf import shortcut_appid, steam_gameid, vdf_decode, vdf_encode


class TestSteamVdf(unittest.TestCase):
    def test_encode_decode_roundtrip(self):
        sample = {
            "shortcuts": {
                "0": {
                    "appid": 12345678,
                    "appname": "Beat Saber VR",
                    "Exe": '"/home/deck/Applications/quest-frame/com.beatgames.beatsaber/launch.sh"',
                    "StartDir": "/home/deck/Applications/quest-frame/com.beatgames.beatsaber",
                    "icon": "",
                    "ShortcutPath": "",
                    "LaunchOptions": "",
                    "IsHidden": 0,
                    "AllowDesktopConfig": 1,
                    "AllowOverlay": 1,
                    "OpenVR": 1,
                    "Devkit": 0,
                    "DevkitGameID": "",
                    "DevkitOverrideAppID": 0,
                    "FlatpakAppID": "",
                    "tags": {
                        "0": "FrameLoad VR",
                        "1": "Rhythm"
                    }
                }
            }
        }
        encoded = vdf_encode(sample)
        self.assertTrue(len(encoded) > 0)
        decoded = vdf_decode(encoded)
        self.assertEqual(decoded["shortcuts"]["0"]["appname"], "Beat Saber VR")
        self.assertEqual(decoded["shortcuts"]["0"]["appid"], 12345678)
        self.assertEqual(decoded["shortcuts"]["0"]["OpenVR"], 1)
        self.assertEqual(decoded["shortcuts"]["0"]["tags"]["0"], "FrameLoad VR")
        self.assertEqual(decoded["shortcuts"]["0"]["tags"]["1"], "Rhythm")

    def test_shortcut_appid(self):
        exe = '"/home/deck/Applications/quest-frame/com.test.app/launch.sh"'
        title = "Test App"
        appid = shortcut_appid(exe, title)
        self.assertIsInstance(appid, int)
        self.assertTrue(appid & 0x80000000 != 0)

        gid = steam_gameid(appid)
        self.assertEqual((gid >> 32) & 0xFFFFFFFF, appid & 0xFFFFFFFF)
        self.assertEqual(gid & 0xFFFFFFFF, 0x02000000)


if __name__ == "__main__":
    unittest.main()
