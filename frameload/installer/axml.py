"""Pure-Python reader for Android binary XML (AndroidManifest.xml) and the part of resources.arsc
needed to resolve an app's label. Standard library only; never trusts sizes read from the file."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

RES_STRING_POOL = 0x0001
RES_TABLE = 0x0002
RES_XML = 0x0003
RES_TABLE_PACKAGE = 0x0200
RES_TABLE_TYPE = 0x0201
XML_START_ELEMENT = 0x0102
XML_END_ELEMENT = 0x0103
XML_RESOURCE_MAP = 0x0180

TYPE_REFERENCE = 0x01
TYPE_STRING = 0x03
TYPE_INT_DEC = 0x10
TYPE_INT_HEX = 0x11
TYPE_INT_BOOLEAN = 0x12

NO_ENTRY = 0xFFFFFFFF
UTF8_FLAG = 0x100

# Release builds often strip attribute names from the string pool and keep only these framework ids.
ATTR_IDS = {
    0x01010001: "label",
    0x01010003: "name",
    0x0101000E: "enabled",
    0x01010024: "value",
    0x01010025: "resource",
    0x01010202: "targetActivity",
    0x0101020C: "minSdkVersion",
    0x0101021B: "versionCode",
    0x0101021C: "versionName",
    0x01010270: "targetSdkVersion",
    0x0101028E: "required",
    0x01010591: "isSplitRequired",
}

ACTION_MAIN = "android.intent.action.MAIN"
CATEGORY_LAUNCHER = "android.intent.category.LAUNCHER"
CATEGORY_INFO = "android.intent.category.INFO"
VR_CATEGORIES = (
    "com.oculus.intent.category.VR",
    "org.khronos.openxr.intent.category.IMMERSIVE_HMD",
)
HAND_TRACKING_FEATURE = "oculus.software.handtracking"
HAND_TRACKING_PERMISSION = "com.oculus.permission.HAND_TRACKING"


class AxmlError(ValueError):
    pass


class ResRef(int):
    """An unresolved @resource reference."""

    def __repr__(self) -> str:
        return f"@0x{int(self):08x}"


@dataclass
class Element:
    tag: str
    attrs: Dict[str, Any] = field(default_factory=dict)
    children: List["Element"] = field(default_factory=list)

    def find_all(self, tag: str) -> List["Element"]:
        return [c for c in self.children if c.tag == tag]

    def find(self, tag: str) -> Optional["Element"]:
        for c in self.children:
            if c.tag == tag:
                return c
        return None


def _pool_string(data: bytes, pool_off: int, index: int) -> str:
    """Decodes one string of the string pool chunk at pool_off."""
    try:
        _, hsize, size, count, _, flags, strings_start, _ = struct.unpack_from("<HHIIIIII", data, pool_off)
        if index < 0 or index >= count or hsize + count * 4 > size:
            return ""
        (rel,) = struct.unpack_from("<I", data, pool_off + hsize + index * 4)
        p = pool_off + strings_start + rel
        end = min(pool_off + size, len(data))
        if p >= end:
            return ""
        if flags & UTF8_FLAG:
            if data[p] & 0x80:  # character count, unused
                p += 1
            p += 1
            n = data[p]
            p += 1
            if n & 0x80:
                n = ((n & 0x7F) << 8) | data[p]
                p += 1
            return data[p:min(p + n, end)].decode("utf-8", errors="replace")
        (n,) = struct.unpack_from("<H", data, p)
        p += 2
        if n & 0x8000:
            (low,) = struct.unpack_from("<H", data, p)
            n = ((n & 0x7FFF) << 16) | low
            p += 2
        return data[p:min(p + n * 2, end)].decode("utf-16-le", errors="replace")
    except (struct.error, IndexError):
        return ""


def parse_axml(data: bytes) -> Element:
    """Parses a binary XML document and returns its root element."""
    if len(data) < 8:
        raise AxmlError("file too short")
    ftype, fhsize, _ = struct.unpack_from("<HHI", data, 0)
    if ftype != RES_XML:
        raise AxmlError("not an Android binary XML file")

    pool_off = -1
    resmap: List[int] = []
    root: Optional[Element] = None
    stack: List[Element] = []
    off = fhsize
    while off + 8 <= len(data):
        ctype, hsize, size = struct.unpack_from("<HHI", data, off)
        if size < 8 or hsize < 8 or off + size > len(data):
            break
        if ctype == RES_STRING_POOL and pool_off < 0:
            pool_off = off
        elif ctype == XML_RESOURCE_MAP:
            resmap = list(struct.unpack_from(f"<{(size - hsize) // 4}I", data, off + hsize))
        elif ctype == XML_START_ELEMENT:
            ext = off + hsize
            _, name, attr_start, attr_size, attr_count = struct.unpack_from("<IIHHH", data, ext)
            el = Element(tag=_pool_string(data, pool_off, name))
            if attr_size >= 20 and ext + attr_start + attr_count * attr_size <= off + size:
                for i in range(attr_count):
                    _, a_name, a_raw, _, _, v_type, v_data = struct.unpack_from(
                        "<IIIHBBI", data, ext + attr_start + i * attr_size)
                    key = ATTR_IDS.get(resmap[a_name]) if a_name < len(resmap) else None
                    key = key or _pool_string(data, pool_off, a_name)
                    if not key:
                        continue
                    if v_type == TYPE_STRING:
                        value: Any = _pool_string(data, pool_off, v_data)
                    elif v_type == TYPE_INT_BOOLEAN:
                        value = v_data != 0
                    elif v_type in (TYPE_INT_DEC, TYPE_INT_HEX):
                        value = v_data
                    elif v_type == TYPE_REFERENCE:
                        value = ResRef(v_data)
                    elif a_raw != NO_ENTRY:
                        value = _pool_string(data, pool_off, a_raw)
                    else:
                        value = v_data
                    el.attrs[key] = value
            if stack:
                stack[-1].children.append(el)
            elif root is None:
                root = el
            stack.append(el)
        elif ctype == XML_END_ELEMENT and stack:
            stack.pop()
        off += size

    if root is None:
        raise AxmlError("no elements found")
    return root


@dataclass
class ManifestInfo:
    package: str = ""
    version_code: str = ""
    version_name: str = ""
    min_sdk: int = 0
    target_sdk: int = 0
    label: str = ""
    label_ref: int = 0
    launch_activity: str = ""   # the activity Lepton starts: a real activity with MAIN + LAUNCHER
    alias_launcher: str = ""    # LAUNCHER exists only on an <activity-alias>, which Lepton ignores
    info_activity: str = ""     # MAIN + INFO, the usual Quest store layout
    categories: Set[str] = field(default_factory=set)
    features: Dict[str, bool] = field(default_factory=dict)  # name -> required
    permissions: Set[str] = field(default_factory=set)
    meta: Dict[str, Any] = field(default_factory=dict)
    split_required: bool = False

    @property
    def is_vr(self) -> bool:
        if any(c in self.categories for c in VR_CATEGORIES):
            return True
        if str(self.meta.get("com.samsung.android.vr.application.mode", "")).lower() == "vr_only":
            return True
        return self.features.get("android.hardware.vr.headtracking", False)

    @property
    def hand_tracking(self) -> str:
        """'required', 'optional' or 'none', as declared by the app."""
        if HAND_TRACKING_FEATURE in self.features:
            return "required" if self.features[HAND_TRACKING_FEATURE] else "optional"
        return "optional" if HAND_TRACKING_PERMISSION in self.permissions else "none"


def _qualify(package: str, name: Any) -> str:
    name = str(name or "")
    if not name:
        return ""
    if name.startswith("."):
        return package + name
    return name if "." in name else f"{package}.{name}"


def read_manifest(data: bytes) -> ManifestInfo:
    """Extracts what FrameLoad needs from a binary AndroidManifest.xml."""
    root = parse_axml(data)
    if root.tag != "manifest":
        raise AxmlError(f"unexpected root element <{root.tag}>")

    info = ManifestInfo(package=str(root.attrs.get("package", "")))
    if "versionCode" in root.attrs:
        info.version_code = str(root.attrs["versionCode"])
    version_name = root.attrs.get("versionName")
    if version_name is not None and not isinstance(version_name, ResRef):
        info.version_name = str(version_name)
    info.split_required = bool(root.attrs.get("isSplitRequired", False))

    sdk = root.find("uses-sdk")
    if sdk is not None:
        for attr, target in (("minSdkVersion", "min_sdk"), ("targetSdkVersion", "target_sdk")):
            if isinstance(sdk.attrs.get(attr), int) and not isinstance(sdk.attrs[attr], bool):
                setattr(info, target, int(sdk.attrs[attr]))

    for feat in root.find_all("uses-feature"):
        name = feat.attrs.get("name")
        if isinstance(name, str) and name:
            info.features[name] = bool(feat.attrs.get("required", True))
    for perm in root.find_all("uses-permission"):
        if isinstance(perm.attrs.get("name"), str):
            info.permissions.add(perm.attrs["name"])

    app = root.find("application")
    if app is None:
        return info

    label = app.attrs.get("label")
    if isinstance(label, ResRef):
        info.label_ref = int(label)
    elif label:
        info.label = str(label)

    def collect_meta(el: Element) -> None:
        for md in el.find_all("meta-data"):
            name = md.attrs.get("name")
            if isinstance(name, str) and name not in info.meta:
                info.meta[name] = md.attrs.get("value", md.attrs.get("resource"))

    collect_meta(app)
    for el in app.children:
        if el.tag not in ("activity", "activity-alias"):
            continue
        collect_meta(el)
        if el.attrs.get("enabled") is False:
            continue
        for flt in el.find_all("intent-filter"):
            actions = {a.attrs.get("name") for a in flt.find_all("action")}
            cats = {c.attrs.get("name") for c in flt.find_all("category") if isinstance(c.attrs.get("name"), str)}
            info.categories |= cats
            if ACTION_MAIN not in actions:
                continue
            if el.tag == "activity":
                name = _qualify(info.package, el.attrs.get("name"))
                if CATEGORY_LAUNCHER in cats and not info.launch_activity:
                    info.launch_activity = name
                elif CATEGORY_INFO in cats and not info.info_activity:
                    info.info_activity = name
            elif CATEGORY_LAUNCHER in cats and not info.alias_launcher:
                info.alias_launcher = _qualify(info.package, el.attrs.get("targetActivity"))
    return info


def resolve_string_resource(arsc: bytes, res_id: int, _depth: int = 0) -> str:
    """Looks up a string resource (e.g. the app label) in resources.arsc, preferring the default locale."""
    if _depth > 4 or len(arsc) < 12:
        return ""
    try:
        ttype, thsize, _ = struct.unpack_from("<HHI", arsc, 0)
        if ttype != RES_TABLE:
            return ""
        want_pkg, want_type, want_entry = res_id >> 24, (res_id >> 16) & 0xFF, res_id & 0xFFFF
        global_pool = -1
        candidates: List[tuple] = []  # (rank, data_type, data)
        off = thsize
        while off + 8 <= len(arsc):
            ctype, hsize, size = struct.unpack_from("<HHI", arsc, off)
            if size < 8 or hsize < 8 or off + size > len(arsc):
                break
            if ctype == RES_STRING_POOL and global_pool < 0:
                global_pool = off
            elif ctype == RES_TABLE_PACKAGE and struct.unpack_from("<I", arsc, off + 8)[0] == want_pkg:
                inner, pkg_end = off + hsize, off + size
                while inner + 8 <= pkg_end:
                    itype, ihsize, isize = struct.unpack_from("<HHI", arsc, inner)
                    if isize < 8 or ihsize < 8 or inner + isize > pkg_end:
                        break
                    if itype == RES_TABLE_TYPE and arsc[inner + 8] == want_type:
                        value = _type_chunk_entry(arsc, inner, ihsize, isize, want_entry)
                        if value is not None:
                            lang = arsc[inner + 28:inner + 30]  # ResTable_config.language
                            rank = 0 if lang == b"\x00\x00" else (1 if lang == b"en" else 2)
                            candidates.append((rank,) + value)
                    inner += isize
            off += size
        for _, data_type, value in sorted(candidates, key=lambda c: c[0]):
            if data_type == TYPE_STRING and global_pool >= 0:
                return _pool_string(arsc, global_pool, value)
            if data_type == TYPE_REFERENCE and value != res_id:
                return resolve_string_resource(arsc, value, _depth + 1)
    except (struct.error, IndexError):
        pass
    return ""


def _type_chunk_entry(arsc: bytes, off: int, hsize: int, size: int, entry: int) -> Optional[tuple]:
    """Returns (data_type, data) of a simple entry in a ResTable_type chunk, or None."""
    flags = arsc[off + 9]
    entry_count, entries_start = struct.unpack_from("<II", arsc, off + 12)
    table = off + hsize
    if flags & 0x01:  # sparse: sorted (index, offset / 4) pairs
        rel = None
        for i in range(entry_count):
            idx, off16 = struct.unpack_from("<HH", arsc, table + i * 4)
            if idx == entry:
                rel = off16 * 4
                break
        if rel is None:
            return None
    elif entry >= entry_count:
        return None
    elif flags & 0x02:  # 16-bit offsets
        (off16,) = struct.unpack_from("<H", arsc, table + entry * 2)
        if off16 == 0xFFFF:
            return None
        rel = off16 * 4
    else:
        (rel,) = struct.unpack_from("<I", arsc, table + entry * 4)
        if rel == NO_ENTRY:
            return None
    pos = off + entries_start + rel
    if pos + 16 > off + size:
        return None
    esize, eflags = struct.unpack_from("<HH", arsc, pos)
    if eflags & 0x0009:  # complex (bag) or compact entries hold no plain string
        return None
    _, _, data_type, value = struct.unpack_from("<HBBI", arsc, pos + esize)
    return data_type, value
