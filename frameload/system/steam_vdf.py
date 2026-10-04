"""Pure-Python Steam binary KeyValues (VDF) decoder and encoder for shortcuts.vdf."""
from __future__ import annotations

import struct
import zlib
from typing import Any, Dict

TYPE_MAP = 0
TYPE_STRING = 1
TYPE_INT = 2
TYPE_END = 8


class VdfError(Exception):
    pass


def shortcut_appid(exe: str, title: str) -> int:
    """Computes standard Steam 32-bit unsigned appid for a non-Steam game shortcut."""
    return zlib.crc32((exe + title).encode("utf-8")) | 0x80000000


def steam_gameid(appid: int) -> int:
    """Computes Steam 64-bit gameid used in steam://rungameid/<gameid>."""
    return (int(appid) << 32) | 0x02000000


def vdf_decode(data: bytes) -> Dict[str, Any]:
    """Decodes binary KeyValues VDF format into a Python dictionary."""
    if not data:
        return {}

    pos = 0

    def read_cstring() -> str:
        nonlocal pos
        try:
            end = data.index(b"\0", pos)
        except ValueError:
            raise VdfError("Malformed VDF: Unterminated string")
        val = data[pos:end].decode("utf-8", "surrogateescape")
        pos = end + 1
        return val

    def read_node() -> Dict[str, Any]:
        nonlocal pos
        out: Dict[str, Any] = {}
        while pos < len(data):
            kind = data[pos]
            pos += 1
            if kind == TYPE_END:
                return out
            key = read_cstring()
            if kind == TYPE_MAP:
                out[key] = read_node()
            elif kind == TYPE_STRING:
                out[key] = read_cstring()
            elif kind == TYPE_INT:
                if pos + 4 > len(data):
                    raise VdfError("Malformed VDF: Unexpected EOF reading integer")
                val = struct.unpack_from("<I", data, pos)[0]
                pos += 4
                out[key] = val
            else:
                raise VdfError(f"Unsupported VDF type {kind} at offset {pos - 1}")
        return out

    root = read_node()
    return root


def vdf_encode(obj: Dict[str, Any]) -> bytes:
    """Encodes a Python dictionary into Steam's binary KeyValues VDF format."""
    out = bytearray()
    for key, value in obj.items():
        key_bytes = key.encode("utf-8", "surrogateescape") + b"\0"
        if isinstance(value, dict):
            out.append(TYPE_MAP)
            out.extend(key_bytes)
            out.extend(vdf_encode(value))
        elif isinstance(value, str):
            out.append(TYPE_STRING)
            out.extend(key_bytes)
            val_bytes = value.encode("utf-8", "surrogateescape") + b"\0"
            out.extend(val_bytes)
        elif isinstance(value, (int, bool)):
            out.append(TYPE_INT)
            out.extend(key_bytes)
            out.extend(struct.pack("<I", int(value) & 0xFFFFFFFF))
        else:
            # Fallback to string for unknown types
            out.append(TYPE_STRING)
            out.extend(key_bytes)
            out.extend(str(value).encode("utf-8", "surrogateescape") + b"\0")
    out.append(TYPE_END)
    return bytes(out)
