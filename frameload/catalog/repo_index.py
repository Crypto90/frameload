"""F-Droid-format repositories: the signed index and the apps in it that Lepton can run.

A repository publishes index-v1.jar: its app list (index-v1.json) in a JAR signed with the repository's
own key (JAR signature scheme v1: MANIFEST.MF, a .SF file and a PKCS#7 block). The list holds each APK's
SHA-256, so a verified index means verified downloads. The check is pure Python: the PKCS#7 block is
read as DER and its RSA PKCS#1 v1.5 signature is checked with pow(), as F-Droid's own clients do.
Every repository probed signs with SHA-1 digests (F-Droid and IzzyOnDroid too), so SHA-1 is accepted
for the JAR signature; the APKs themselves are checked with SHA-256.

Only index format v1 is read today (every repository still serves it). A v2 reader would sit beside
read_index_v1() and parse_index() and produce the same CatalogGame entries.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import re
import urllib.parse
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .models import CatalogGame

FDROID_REPO = "https://f-droid.org/repo"
INDEX_V1_JAR = "index-v1.jar"
INDEX_V1_JSON = "index-v1.json"

# index-v1.json of F-Droid's main repository is about 67 MB; its jar about 16 MB.
MAX_INDEX_JSON_BYTES = 192 * 1024 * 1024
MAX_SIGNATURE_FILE_BYTES = 1024 * 1024  # MANIFEST.MF, the .SF file and the signature block
MIN_RSA_BITS = 2048

# Lepton runs 64-bit ARM apps only, on Android images up to API 34.
LEPTON_ABI = "arm64-v8a"
LEPTON_MAX_SDK = 34
LOCALES = ("en-US", "en-GB", "en")
SCREENSHOT_KINDS = ("phoneScreenshots", "sevenInchScreenshots", "tenInchScreenshots")
MAX_SCREENSHOTS = 10

# Google's own services (offered by microG's repository) are system components, useless when Lepton
# runs one APK per container. Xposed modules need a rooted framework Lepton does not have.
DENY_PACKAGES = frozenset({"com.google.android.gms", "com.google.android.gsf", "com.android.vending"})
HIDDEN_CATEGORIES = frozenset({"Xposed"})

PACKAGE_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-]{0,254}")
HEX64_RE = re.compile(r"[0-9a-f]{64}")


class RepoIndexError(ValueError):
    """The index cannot be used (too large, not an index, missing)."""


class IndexSignatureError(RepoIndexError):
    """The index is not signed, or not by the expected key."""


# ----------------------------------------------------------------------------- fingerprints

def normalize_fingerprint(text: Any) -> str:
    """'43:23:8D 51…' -> '43238d51…': case, spaces and colons do not matter."""
    return re.sub(r"[\s:]", "", str(text or "")).lower()


def is_fingerprint(text: str) -> bool:
    return bool(HEX64_RE.fullmatch(text or ""))


# ----------------------------------------------------------------------------- DER

OID_SIGNED_DATA = bytes.fromhex("2a864886f70d010702")
OID_MESSAGE_DIGEST = bytes.fromhex("2a864886f70d010904")
OID_RSA = bytes.fromhex("2a864886f70d010101")
DIGEST_OIDS = {
    bytes.fromhex("2b0e03021a"): "sha1",
    bytes.fromhex("608648016503040201"): "sha256",
    bytes.fromhex("608648016503040202"): "sha384",
    bytes.fromhex("608648016503040203"): "sha512",
}
RSA_SIGNATURE_OIDS = {
    bytes.fromhex("2a864886f70d010105"): "sha1",
    bytes.fromhex("2a864886f70d01010b"): "sha256",
    bytes.fromhex("2a864886f70d01010c"): "sha384",
    bytes.fromhex("2a864886f70d01010d"): "sha512",
}
DIGEST_INFO = {  # DER prefix of DigestInfo for PKCS#1 v1.5
    "sha1": bytes.fromhex("3021300906052b0e03021a05000414"),
    "sha256": bytes.fromhex("3031300d060960864801650304020105000420"),
    "sha384": bytes.fromhex("3041300d060960864801650304020205000430"),
    "sha512": bytes.fromhex("3051300d060960864801650304020305000440"),
}

Node = Tuple[int, int, int, int]  # tag, start of the element, start and end of its content


def _malformed(what: str) -> IndexSignatureError:
    return IndexSignatureError(f"The index signature is malformed ({what}).")


def _tlv(buf: bytes, pos: int, end: int) -> Tuple[int, int, int]:
    if pos + 2 > end:
        raise _malformed("truncated")
    tag, length = buf[pos], buf[pos + 1]
    pos += 2
    if tag & 0x1F == 0x1F:
        raise _malformed("unexpected tag")
    if length & 0x80:
        count = length & 0x7F
        if count == 0 or count > 4 or pos + count > end:  # no indefinite or absurd lengths
            raise _malformed("bad length")
        length = int.from_bytes(buf[pos:pos + count], "big")
        pos += count
    if pos + length > end:
        raise _malformed("truncated")
    return tag, pos, pos + length


def _kids(buf: bytes, start: int, end: int) -> List[Node]:
    out, pos = [], start
    while pos < end:
        tag, cs, ce = _tlv(buf, pos, end)
        out.append((tag, pos, cs, ce))
        pos = ce
    return out


def _expect(node: Node, tag: int, what: str) -> Node:
    if node[0] != tag:
        raise _malformed(what)
    return node


def _value(buf: bytes, node: Node) -> bytes:
    return buf[node[2]:node[3]]


def _algorithm(buf: bytes, node: Node) -> bytes:
    """The OID of an AlgorithmIdentifier."""
    _expect(node, 0x30, "algorithm")
    kids = _kids(buf, node[2], node[3])
    if not kids:
        raise _malformed("algorithm")
    return _value(buf, _expect(kids[0], 0x06, "algorithm"))


def _rsa_public_key(cert: bytes) -> Tuple[int, int]:
    """Modulus and exponent of an X.509 certificate's RSA key."""
    _, cs, ce = _tlv(cert, 0, len(cert))
    parts = _kids(cert, cs, ce)
    if len(parts) != 3:
        raise _malformed("certificate")
    tbs = _expect(parts[0], 0x30, "certificate")
    fields = _kids(cert, tbs[2], tbs[3])
    if fields and fields[0][0] == 0xA0:  # explicit version
        fields = fields[1:]
    if len(fields) < 6:
        raise _malformed("certificate")
    spki = _expect(fields[5], 0x30, "public key")  # serial, signature, issuer, validity, subject, key
    alg, bits = (_kids(cert, spki[2], spki[3]) + [None, None])[:2]
    if not alg or not bits or _algorithm(cert, alg) != OID_RSA:
        raise IndexSignatureError("The index is not signed with an RSA key.")
    _expect(bits, 0x03, "public key")
    key = cert[bits[2] + 1:bits[3]]  # skip the unused-bits byte
    _, ks, ke = _tlv(key, 0, len(key))
    numbers = _kids(key, ks, ke)
    if len(numbers) != 2:
        raise _malformed("public key")
    n = int.from_bytes(_value(key, _expect(numbers[0], 0x02, "modulus")), "big")
    e = int.from_bytes(_value(key, _expect(numbers[1], 0x02, "exponent")), "big")
    if n.bit_length() < MIN_RSA_BITS or e < 3 or e % 2 == 0:
        raise IndexSignatureError("The index is signed with a key that is too weak.")
    return n, e


def _rsa_verify(n: int, e: int, signature: bytes, digest_name: str, digest: bytes) -> None:
    k = (n.bit_length() + 7) // 8
    s = int.from_bytes(signature, "big")
    if len(signature) != k or s >= n:
        raise IndexSignatureError("The index signature is invalid.")
    t = DIGEST_INFO[digest_name] + digest
    if k < len(t) + 11:
        raise IndexSignatureError("The index is signed with a key that is too weak.")
    expected = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    if not hmac.compare_digest(pow(s, e, n).to_bytes(k, "big"), expected):
        raise IndexSignatureError("The index signature is invalid.")


def _signer(blob: bytes) -> Dict[str, Any]:
    """The one certificate and the one SignerInfo of a detached PKCS#7 signature block."""
    tag, cs, ce = _tlv(blob, 0, len(blob))
    if tag != 0x30 or ce != len(blob):
        raise _malformed("signature block")
    info = _kids(blob, cs, ce)
    if len(info) != 2 or _value(blob, _expect(info[0], 0x06, "content type")) != OID_SIGNED_DATA:
        raise _malformed("not a PKCS#7 signature")
    tag, sds, sde = _tlv(blob, _expect(info[1], 0xA0, "signed data")[2], info[1][3])
    if tag != 0x30:
        raise _malformed("signed data")
    signed_data = _kids(blob, sds, sde)
    cert_sets = [k for k in signed_data if k[0] == 0xA0]
    if len(cert_sets) != 1:
        raise IndexSignatureError("The index signature carries no certificate.")
    certs = _kids(blob, cert_sets[0][2], cert_sets[0][3])
    if len(certs) != 1:
        raise IndexSignatureError("The index signature must carry exactly one certificate.")
    signer_set = _expect(signed_data[-1], 0x31, "signer infos")
    signer_infos = _kids(blob, signer_set[2], signer_set[3])
    if len(signer_infos) != 1:
        raise IndexSignatureError("The index must be signed exactly once.")
    si = _kids(blob, _expect(signer_infos[0], 0x30, "signer info")[2], signer_infos[0][3])
    if len(si) < 5:
        raise _malformed("signer info")
    pos = 3
    attrs = None
    if si[pos][0] == 0xA0:
        attrs = si[pos]
        pos += 1
    if len(si) < pos + 2:
        raise _malformed("signer info")
    return {
        "cert": blob[certs[0][1]:certs[0][3]],
        "digest_oid": _algorithm(blob, si[2]),
        "attrs": attrs,
        "sig_oid": _algorithm(blob, si[pos]),
        "signature": _value(blob, _expect(si[pos + 1], 0x04, "signature")),
        "blob": blob,
    }


def _message_digest(blob: bytes, attrs: Node) -> bytes:
    """The messageDigest attribute among the signed attributes (it must be there exactly once)."""
    found = []
    for attr in _kids(blob, attrs[2], attrs[3]):
        parts = _kids(blob, _expect(attr, 0x30, "attribute")[2], attr[3])
        if len(parts) != 2:
            raise _malformed("attribute")
        if _value(blob, _expect(parts[0], 0x06, "attribute")) == OID_MESSAGE_DIGEST:
            values = _kids(blob, _expect(parts[1], 0x31, "attribute")[2], parts[1][3])
            if len(values) != 1:
                raise _malformed("message digest")
            found.append(_value(blob, _expect(values[0], 0x04, "message digest")))
    if len(found) != 1:
        raise _malformed("message digest")
    return found[0]


# ----------------------------------------------------------------------------- JAR manifests

DIGEST_HEADERS = (("SHA-512", "sha512"), ("SHA-384", "sha384"), ("SHA-256", "sha256"), ("SHA1", "sha1"), ("SHA-1", "sha1"))


def _sections(raw: bytes) -> List[Tuple[Dict[str, str], bytes]]:
    """Sections of a manifest or .SF file: (headers, the exact bytes jarsigner hashed, which include
    the blank line that ends the section)."""
    sections: List[Tuple[Dict[str, str], bytes]] = []
    lines: List[bytes] = []

    def close() -> None:
        if any(line.strip() for line in lines):
            headers: Dict[str, str] = {}
            joined: List[str] = []
            for line in lines:
                try:
                    text = line.rstrip(b"\r\n").decode("utf-8")
                except UnicodeDecodeError:
                    raise _malformed("manifest") from None
                if text.startswith(" ") and joined:
                    joined[-1] += text[1:]  # continuation of a line longer than 72 bytes
                elif text:
                    joined.append(text)
            for text in joined:
                name, sep, value = text.partition(": ")
                if not sep or name in headers:
                    raise _malformed("manifest")
                headers[name] = value
            sections.append((headers, b"".join(lines)))
        lines.clear()

    for line in raw.splitlines(keepends=True):
        lines.append(line)
        if line in (b"\r\n", b"\n", b"\r"):
            close()
    close()
    return sections


def _named(sections: List[Tuple[Dict[str, str], bytes]], name: str) -> Optional[Tuple[Dict[str, str], bytes]]:
    found = [s for s in sections[1:] if s[0].get("Name") == name]
    if len(found) > 1:
        raise _malformed(f"{name} is listed twice")
    return found[0] if found else None


def _digests_match(headers: Dict[str, str], suffix: str, data: bytes) -> Optional[bool]:
    """None when no known digest is listed; otherwise whether every listed one matches."""
    listed = [(algo, headers[name + suffix]) for name, algo in DIGEST_HEADERS if name + suffix in headers]
    if not listed:
        return None
    try:
        return all(base64.b64decode(value, validate=True) == hashlib.new(algo, data).digest() for algo, value in listed)
    except ValueError:
        return False


def _read_member(z: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    if info.file_size > limit:
        raise RepoIndexError(f"{info.filename} is larger than expected.")
    with z.open(info) as f:
        data = f.read(limit + 1)
    if len(data) > limit:
        raise RepoIndexError(f"{info.filename} is larger than expected.")
    return data


def verify_index_jar(data: bytes, entry: str = INDEX_V1_JSON, fingerprint: str = "",
                     max_bytes: int = MAX_INDEX_JSON_BYTES) -> Tuple[str, bytes]:
    """Checks a repository's signed JAR and returns (signer fingerprint, verified bytes of `entry`).

    The fingerprint is the SHA-256 of the signing certificate, as F-Droid publishes it. With
    `fingerprint` given, a JAR signed by any other key is refused. Raises IndexSignatureError or
    RepoIndexError."""
    want = normalize_fingerprint(fingerprint)
    if want and not is_fingerprint(want):
        raise IndexSignatureError("The signing key fingerprint must be 64 hexadecimal characters.")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise RepoIndexError("The download is not a repository index.") from None
    with z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        if len(set(names)) != len(names):
            raise IndexSignatureError("The index contains the same file twice.")
        try:
            entry_info = z.getinfo(entry)
        except KeyError:
            raise RepoIndexError(f"The download contains no {entry}.") from None
        # Declared sizes are checked before anything is unpacked: a small download cannot become a huge file.
        if entry_info.file_size > max_bytes:
            raise RepoIndexError(f"{entry} is larger than FrameLoad accepts ({entry_info.file_size // (1024 * 1024)} MB).")

        meta = {n for n in names if n.startswith("META-INF/") and "/" not in n[len("META-INF/"):]}
        blocks = [n for n in meta if n.upper().endswith((".RSA", ".DSA", ".EC"))]
        if not blocks:
            raise IndexSignatureError("The index is not signed.")
        if len(blocks) > 1 or len([n for n in meta if n.upper().endswith(".SF")]) > 1:
            raise IndexSignatureError("The index must be signed exactly once.")
        if not blocks[0].upper().endswith(".RSA"):
            raise IndexSignatureError("The index is not signed with an RSA key.")
        sf_name = blocks[0][:-4] + ".SF"
        if sf_name not in meta or "META-INF/MANIFEST.MF" not in meta:
            raise IndexSignatureError("The index signature is incomplete.")
        block = _read_member(z, z.getinfo(blocks[0]), MAX_SIGNATURE_FILE_BYTES)
        sf = _read_member(z, z.getinfo(sf_name), MAX_SIGNATURE_FILE_BYTES)
        manifest = _read_member(z, z.getinfo("META-INF/MANIFEST.MF"), MAX_SIGNATURE_FILE_BYTES)

        # 1. The signature block: whose key, and does it sign the .SF file?
        signer = _signer(block)
        found = hashlib.sha256(signer["cert"]).hexdigest()
        if want and want != found:
            raise IndexSignatureError(f"The index is signed by a different key ({found}, expected {want}).")
        n, e = _rsa_public_key(signer["cert"])
        digest_name = DIGEST_OIDS.get(signer["digest_oid"])
        if not digest_name:
            raise IndexSignatureError("The index signature uses an unsupported digest.")
        if signer["sig_oid"] == OID_RSA:
            sig_digest = digest_name
        elif signer["sig_oid"] in RSA_SIGNATURE_OIDS:
            sig_digest = RSA_SIGNATURE_OIDS[signer["sig_oid"]]
        else:
            raise IndexSignatureError("The index signature uses an unsupported algorithm.")
        if signer["attrs"] is not None:
            # The signature covers the signed attributes (as a SET); one of them is the digest of the .SF file.
            attrs = signer["attrs"]
            if not hmac.compare_digest(_message_digest(signer["blob"], attrs), hashlib.new(digest_name, sf).digest()):
                raise IndexSignatureError("The index signature does not match its signature file.")
            signed = b"\x31" + signer["blob"][attrs[1] + 1:attrs[3]]
        else:
            signed = sf
        _rsa_verify(n, e, signer["signature"], sig_digest, hashlib.new(sig_digest, signed).digest())

        # 2. The .SF file covers the manifest (whole, or the entry's section of it).
        sf_sections = _sections(sf)
        manifest_sections = _sections(manifest)
        if not sf_sections or not manifest_sections:
            raise _malformed("manifest")
        if not _digests_match(sf_sections[0][0], "-Digest-Manifest", manifest):
            sf_entry, man_entry = _named(sf_sections, entry), _named(manifest_sections, entry)
            if not sf_entry or not man_entry:
                raise IndexSignatureError(f"{entry} is not covered by the index signature.")
            if not _digests_match(sf_entry[0], "-Digest", man_entry[1]):
                raise IndexSignatureError("The index manifest does not match its signature.")

        # 3. The manifest lists the entry's digest.
        man_entry = _named(manifest_sections, entry)
        if not man_entry:
            raise IndexSignatureError(f"{entry} is not covered by the index signature.")
        content = _read_member(z, entry_info, max_bytes)
        match = _digests_match(man_entry[0], "-Digest", content)
        if not match:
            raise IndexSignatureError("The index content does not match its signature." if match is False
                                      else f"The index manifest lists no digest for {entry}.")
        return found, content


def read_index_v1(data: bytes, fingerprint: str = "", max_json: int = MAX_INDEX_JSON_BYTES) -> Tuple[str, Dict[str, Any]]:
    """Verifies index-v1.jar and returns (signer fingerprint, the parsed index-v1.json)."""
    found, content = verify_index_jar(data, INDEX_V1_JSON, fingerprint, max_json)
    try:
        index = json.loads(content)
    except ValueError:
        raise RepoIndexError("The repository index is not valid JSON.") from None
    finally:
        del content
    if not isinstance(index, dict) or not isinstance(index.get("repo"), dict):
        raise RepoIndexError("The download is not an F-Droid repository index.")
    return found, index


def repo_mirrors(repo: Dict[str, Any], primary: str) -> List[str]:
    """The https mirrors a signed index names (onion and http ones cannot be used here)."""
    out: List[str] = []
    for url in repo.get("mirrors") or []:
        if not isinstance(url, str):
            continue
        url = url.strip().rstrip("/")
        parts = urllib.parse.urlsplit(url)
        if (parts.scheme == "https" and parts.hostname and not parts.username and not parts.password
                and not parts.hostname.endswith(".onion") and url != primary.rstrip("/") and url not in out):
            out.append(url)
    return out[:20]


# ----------------------------------------------------------------------------- the apps in an index

def _version_code(release: Dict[str, Any]) -> int:
    try:
        return int(release.get("versionCode", 0))
    except (TypeError, ValueError):
        return -1


def _sha256(release: Dict[str, Any]) -> str:
    value = str(release.get("hash") or "").lower()
    return value if release.get("hashType", "sha256") == "sha256" and HEX64_RE.fullmatch(value) else ""


def _safe_path(name: Any) -> str:
    """A file name from the index as a path below the repository, or '' (no '..', query, scheme)."""
    if not isinstance(name, str) or not name or len(name) > 512 or name.startswith("/"):
        return ""
    if any(ch in name for ch in "\\?#:") or any(ord(ch) < 32 for ch in name):
        return ""
    if any(part in ("", ".", "..") for part in name.split("/")):
        return ""
    return urllib.parse.quote(name, safe="/!$&'()*+,;=@")


def _is_compatible(release: Dict[str, Any]) -> bool:
    native = release.get("nativecode") or []
    if native and LEPTON_ABI not in native:
        return False
    try:
        if int(release.get("minSdkVersion", 1)) > LEPTON_MAX_SDK:
            return False
    except (TypeError, ValueError):
        pass
    try:  # an app that declares it stops before Android 14 cannot be installed there
        if release.get("maxSdkVersion") is not None and int(release["maxSdkVersion"]) < LEPTON_MAX_SDK:
            return False
    except (TypeError, ValueError):
        pass
    return True


def pick_release(app: Dict[str, Any], releases: Sequence[Any]) -> Optional[Dict[str, Any]]:
    """The release to offer: the repository's suggested version if Lepton can run it, else the newest
    compatible one at or below it (releases above the suggested version are betas). Releases without
    a SHA-256 cannot be checked after the download and are never offered."""
    usable = [r for r in releases if isinstance(r, dict) and _safe_path(r.get("apkName")) and _sha256(r)
              and _version_code(r) >= 0 and _is_compatible(r)]
    if not usable:
        return None
    usable.sort(key=_version_code, reverse=True)
    try:
        suggested = int(app.get("suggestedVersionCode") or 0)
    except (TypeError, ValueError):
        suggested = 0
    if suggested:
        for r in usable:
            if _version_code(r) <= suggested:
                return r
    return usable[0]


def _localized(app: Dict[str, Any], key: str) -> str:
    loc = app.get("localized") or {}
    for name in LOCALES:
        value = (loc.get(name) or {}).get(key)
        if value:
            return str(value)
    return str(app.get(key) or "")


def _icon_url(app: Dict[str, Any], pkg: str, base: str) -> str:
    loc = app.get("localized") or {}
    for name in LOCALES:
        icon = _safe_path((loc.get(name) or {}).get("icon"))
        if icon:
            return f"{base}/{pkg}/{name}/{icon}"
    icon = _safe_path(app.get("icon"))
    return f"{base}/icons-640/{icon}" if icon else ""


def _screenshots(app: Dict[str, Any], pkg: str, base: str) -> List[str]:
    """Screenshot addresses from the first locale that has any (they live under the repo by locale)."""
    loc = app.get("localized") or {}
    for name in LOCALES:
        entry = loc.get(name) or {}
        found = [f"{base}/{pkg}/{name}/{kind}/{_safe_path(file)}"
                 for kind in SCREENSHOT_KINDS for file in (entry.get(kind) or []) if _safe_path(file)]
        if found:
            return found[:MAX_SCREENSHOTS]
    return []


def release_name_for(source: str, package: str) -> str:
    """F-Droid's entries keep the ids they always had (md5 of the package); other sources get their own,
    so the same package from two repositories is two catalog entries."""
    return package if source == "fdroid" else f"{source}/{package}"


def parse_index(index: Dict[str, Any], base_url: str = FDROID_REPO, source: str = "fdroid",
                source_name: str = "F-Droid") -> List[CatalogGame]:
    """Turns an index-v1 document into catalog entries Lepton can install; every address points below
    `base_url`."""
    base = base_url.rstrip("/")
    packages = index.get("packages") if isinstance(index.get("packages"), dict) else {}
    games: List[CatalogGame] = []
    for app in index.get("apps") or []:
        if not isinstance(app, dict):
            continue
        pkg = app.get("packageName") or ""
        if not isinstance(pkg, str) or not PACKAGE_RE.fullmatch(pkg) or ".." in pkg or pkg in DENY_PACKAGES:
            continue
        categories = [str(c) for c in (app.get("categories") or []) if isinstance(c, str)]
        if HIDDEN_CATEGORIES.intersection(categories):
            continue
        releases = packages.get(pkg)
        release = pick_release(app, releases) if isinstance(releases, list) else None
        if not release:
            continue
        updated_ms = app.get("lastUpdated") or release.get("added") or 0
        try:
            updated = datetime.fromtimestamp(float(updated_ms) / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d") if updated_ms else ""
        except (TypeError, ValueError, OverflowError, OSError):
            updated = ""
        signer = str(release.get("signer") or "").lower()
        video = _localized(app, "video")
        try:
            size = max(0, int(release.get("size") or 0))
        except (TypeError, ValueError):
            size = 0
        games.append(CatalogGame(
            name=_localized(app, "name") or pkg,
            release_name=release_name_for(source, pkg),
            package_name=pkg,
            version_code=str(_version_code(release)),
            version_name=str(release.get("versionName", "")),
            last_updated=updated,
            size_bytes=size,
            thumbnail_url=_icon_url(app, pkg, base),
            kind="flat",
            download_url=f"{base}/{_safe_path(release['apkName'])}",
            sha256=_sha256(release),
            summary=_localized(app, "summary"),
            description=_localized(app, "description"),
            categories=categories,
            license=str(app.get("license") or ""),
            anti_features=[str(a) for a in (app.get("antiFeatures") or []) if isinstance(a, str)],
            screenshots=_screenshots(app, pkg, base),
            video=video if video.startswith("https://") else "",
            source=source,
            source_name=source_name,
            signer=signer if HEX64_RE.fullmatch(signer) else "",
        ))
    return games
