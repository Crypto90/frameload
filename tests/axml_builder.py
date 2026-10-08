"""Test helper: encodes Android binary XML and a one-string resources.arsc, and builds APKs from them."""
from __future__ import annotations

import struct
import zipfile
from typing import Any, Dict, Iterable, List, Optional, Tuple

from frameload.installer.axml import ATTR_IDS

Node = Tuple[str, Dict[str, Any], list]
_ATTR_ID_BY_NAME = {name: res_id for res_id, name in ATTR_IDS.items()}
NONE = 0xFFFFFFFF
LABEL_RES_ID = 0x7F010000


def ref(res_id: int) -> Tuple[str, int]:
    return ("ref", res_id)


def _string_pool(strings: List[str]) -> bytes:
    offsets, blob = [], b""
    for text in strings:
        offsets.append(len(blob))
        blob += struct.pack("<H", len(text)) + text.encode("utf-16-le") + b"\x00\x00"
    blob += b"\x00" * (-len(blob) % 4)
    header_size = 28
    strings_start = header_size + 4 * len(strings)
    return (struct.pack("<HHIIIIII", 0x0001, header_size, strings_start + len(blob), len(strings), 0, 0, strings_start, 0)
            + struct.pack(f"<{len(strings)}I", *offsets) + blob)


def build_axml(root: Node, strip_attr_names: bool = False) -> bytes:
    """root is (tag, {attr: value}, [children]). Values: str, bool, int, or ref(id)."""
    attr_names: List[str] = []
    others: List[str] = []

    def collect(node: Node) -> None:
        tag, attrs, children = node
        for name, value in attrs.items():
            if name in _ATTR_ID_BY_NAME and name not in attr_names:
                attr_names.append(name)
        for child in children:
            collect(child)

    def collect_others(node: Node) -> None:
        tag, attrs, children = node
        for text in [tag] + [n for n in attrs if n not in _ATTR_ID_BY_NAME] + [v for v in attrs.values() if isinstance(v, str)]:
            if text not in others:
                others.append(text)
        for child in children:
            collect_others(child)

    collect(root)
    collect_others(root)
    # Framework attribute names come first so the resource map lines up with them.
    pool_strings = [("" if strip_attr_names else n) for n in attr_names] + others
    index = {n: i for i, n in enumerate(attr_names)}
    for i, text in enumerate(others):
        index.setdefault(("s", text), len(attr_names) + i)

    def sidx(text: str) -> int:
        return index[("s", text)]

    body = b""

    def emit(node: Node) -> None:
        nonlocal body
        tag, attrs, children = node
        encoded = b""
        for name, value in attrs.items():
            name_idx = index[name] if name in _ATTR_ID_BY_NAME else sidx(name)
            raw = NONE
            if isinstance(value, tuple):
                vtype, data = 0x01, value[1]
            elif isinstance(value, bool):
                vtype, data = 0x12, NONE if value else 0
            elif isinstance(value, int):
                vtype, data = 0x10, value
            else:
                vtype, data = 0x03, sidx(value)
                raw = data
            encoded += struct.pack("<IIIHBBI", NONE, name_idx, raw, 8, 0, vtype, data)
        body += struct.pack("<HHIII", 0x0102, 16, 36 + len(encoded), 1, NONE)
        body += struct.pack("<IIHHHHHH", NONE, sidx(tag), 20, 20, len(attrs), 0, 0, 0) + encoded
        for child in children:
            emit(child)
        body += struct.pack("<HHIIIII", 0x0103, 16, 24, 1, NONE, NONE, sidx(tag))

    emit(root)
    resmap = struct.pack("<HHI", 0x0180, 8, 8 + 4 * len(attr_names))
    resmap += struct.pack(f"<{len(attr_names)}I", *[_ATTR_ID_BY_NAME[n] for n in attr_names])
    payload = _string_pool(pool_strings) + resmap + body
    return struct.pack("<HHI", 0x0003, 8, 8 + len(payload)) + payload


def build_arsc(label: str) -> bytes:
    """A resource table whose only entry, LABEL_RES_ID, is the string `label`."""
    entry = struct.pack("<HHI", 8, 0, 0) + struct.pack("<HBBI", 8, 0, 0x03, 0)
    type_header_size = 20 + 64
    type_chunk = struct.pack("<HHIBBHII", 0x0201, type_header_size, type_header_size + 4 + len(entry),
                             1, 0, 0, 1, type_header_size + 4)
    type_chunk += struct.pack("<I", 64) + b"\x00" * 60 + struct.pack("<I", 0) + entry
    package_header_size = 288
    package = struct.pack("<HHII", 0x0200, package_header_size, package_header_size + len(type_chunk), 0x7F)
    package += b"\x00" * 256 + struct.pack("<IIIII", 0, 0, 0, 0, 0) + type_chunk
    payload = _string_pool([label]) + package
    return struct.pack("<HHII", 0x0002, 12, 12 + len(payload), 1) + payload


def manifest(package: str, *, version_code: int = 7, version_name: str = "1.2.3",
             categories: Iterable[str] = ("android.intent.category.LAUNCHER",), label: Any = None,
             features: Optional[Dict[str, bool]] = None, permissions: Iterable[str] = (),
             alias_launcher: bool = False, activity: str = ".MainActivity", min_sdk: int = 29) -> Node:
    """A typical single-activity manifest."""
    filters = [("intent-filter", {}, [("action", {"name": "android.intent.action.MAIN"}, [])]
                + [("category", {"name": c}, []) for c in categories])]
    app_children: list = [("activity", {"name": activity}, [] if alias_launcher else filters)]
    if alias_launcher:
        app_children.append(("activity-alias", {"name": ".Launcher", "targetActivity": activity}, filters))
    app_attrs: Dict[str, Any] = {}
    if label is not None:
        app_attrs["label"] = label
    children: list = [("uses-sdk", {"minSdkVersion": min_sdk, "targetSdkVersion": 32}, [])]
    children += [("uses-feature", {"name": n, "required": r}, []) for n, r in (features or {}).items()]
    children += [("uses-permission", {"name": p}, []) for p in permissions]
    children.append(("application", app_attrs, app_children))
    return ("manifest", {"package": package, "versionCode": version_code, "versionName": version_name}, children)


def write_apk(path: str, manifest_node: Optional[Node] = None, libs: Iterable[str] = (), abi: str = "arm64-v8a",
              arsc: Optional[bytes] = None, raw_manifest: Optional[bytes] = None, **axml_options: Any) -> str:
    with zipfile.ZipFile(path, "w") as zf:
        if raw_manifest is not None:
            zf.writestr("AndroidManifest.xml", raw_manifest)
        elif manifest_node is not None:
            zf.writestr("AndroidManifest.xml", build_axml(manifest_node, **axml_options))
        if arsc is not None:
            zf.writestr("resources.arsc", arsc)
        for lib in libs:
            zf.writestr(f"lib/{abi}/{lib}", b"\x7fELF")
        zf.writestr("classes.dex", b"dex")
    return path
