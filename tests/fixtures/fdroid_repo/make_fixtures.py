"""Builds the signed repository index fixtures of tests/test_app_sources.py.

  python tests/fixtures/fdroid_repo/make_fixtures.py [JDK_HOME]

Needs a JDK (keytool, jarsigner; Java 17 from the Android SDK or Eclipse Adoptium works) and openssl.
Two throwaway RSA-2048 keys are made in a temporary folder and thrown away afterwards, so running it
again changes the fingerprints: paste the printed ones into FIXTURE_FINGERPRINT / OTHER_FINGERPRINT in
tests/test_app_sources.py.

Files written next to this script:
  index-v1.json               the repository index (apps that do and do not run on the Frame)
  index-v1.jar                signed like F-Droid and IzzyOnDroid: SHA-1 digests, sha1WithRSA, signed attributes
  index-v1-sha256.jar         SHA-256 digests and sha256WithRSA
  index-v1-noattr.jar         signed like Guardian Project: no signed attributes, rsaEncryption
  index-v1-two-signers.jar    index-v1.jar signed a second time by another key
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PASSWORD = "frameload-test"

INDEX = {
    "repo": {
        "name": "FrameLoad Test Repo",
        "timestamp": 1760000000000,
        "version": 20002,
        "address": "https://repo.example.org/fdroid/repo",
        "description": "Apps for FrameLoad's tests.",
        "mirrors": ["https://mirror.example.net/fdroid/repo", "http://plain.example.net/fdroid/repo",
                    "http://abcdefghijklmnop.onion/fdroid/repo"],
    },
    "apps": [
        {"packageName": "org.example.notes", "suggestedVersionCode": "20", "categories": ["Writing"],
         "license": "GPL-3.0-only", "lastUpdated": 1750000000000, "antiFeatures": ["NonFreeNet"],
         "localized": {"en-US": {"name": "Pocket Notes", "summary": "Plain text notes", "description": "Long text",
                                 "icon": "icon.png", "phoneScreenshots": ["1.png"]}}},
        {"packageName": "org.example.x86only", "suggestedVersionCode": "1", "name": "x86 Only"},
        {"packageName": "com.google.android.gms", "suggestedVersionCode": "1", "name": "microG Services"},
        {"packageName": "org.example.module", "suggestedVersionCode": "1", "name": "Some Module", "categories": ["Xposed"]},
        {"packageName": "org.example.oldsdk", "suggestedVersionCode": "1", "name": "Old SDK"},
        {"packageName": "org.example.newsdk", "suggestedVersionCode": "1", "name": "New SDK"},
    ],
    "packages": {
        "org.example.notes": [
            {"versionCode": 21, "versionName": "2.1-beta", "apkName": "org.example.notes_21.apk", "hash": "b" * 64,
             "hashType": "sha256", "size": 2100, "minSdkVersion": 24, "signer": "c" * 64},
            {"versionCode": 20, "versionName": "2.0", "apkName": "org.example.notes_20.apk", "hash": "a" * 64,
             "hashType": "sha256", "size": 2000, "minSdkVersion": 24, "signer": "c" * 64},
            {"versionCode": 19, "versionName": "1.9", "apkName": "org.example.notes_19.apk", "hash": "9" * 64,
             "hashType": "sha256", "size": 1900, "signer": "c" * 64},
        ],
        "org.example.x86only": [
            {"versionCode": 1, "apkName": "x86_1.apk", "hash": "e" * 64, "hashType": "sha256", "size": 1,
             "nativecode": ["x86_64"]},
        ],
        "com.google.android.gms": [
            {"versionCode": 1, "apkName": "gms_1.apk", "hash": "f" * 64, "hashType": "sha256", "size": 1},
        ],
        "org.example.module": [
            {"versionCode": 1, "apkName": "module_1.apk", "hash": "1" * 64, "hashType": "sha256", "size": 1},
        ],
        "org.example.oldsdk": [
            {"versionCode": 1, "apkName": "oldsdk_1.apk", "hash": "2" * 64, "hashType": "sha256", "size": 1,
             "maxSdkVersion": 29},
        ],
        "org.example.newsdk": [
            {"versionCode": 1, "apkName": "newsdk_1.apk", "hash": "3" * 64, "hashType": "sha256", "size": 1,
             "minSdkVersion": 31},
        ],
    },
}


def run(*cmd: str) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def main() -> None:
    jdk = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("JAVA_HOME", "")
    keytool = os.path.join(jdk, "bin", "keytool") if jdk else "keytool"
    jarsigner = os.path.join(jdk, "bin", "jarsigner") if jdk else "jarsigner"
    tmp = tempfile.mkdtemp()
    try:
        stores = {"repokey": os.path.join(tmp, "repo.p12"), "otherkey": os.path.join(tmp, "other.p12")}
        for alias, cn in (("repokey", "FrameLoad Test Repo"), ("otherkey", "Someone Else")):
            run(keytool, "-genkeypair", "-keystore", stores[alias], "-storetype", "PKCS12", "-storepass", PASSWORD,
                "-alias", alias, "-keyalg", "RSA", "-keysize", "2048", "-validity", "36500", "-dname", f"CN={cn}")
        store = stores["repokey"]

        json_path = os.path.join(HERE, "index-v1.json")
        with open(json_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(INDEX, f, indent=1)
        unsigned = os.path.join(tmp, "unsigned.jar")
        with zipfile.ZipFile(unsigned, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(json_path, "index-v1.json")

        def sign(src: str, dest: str, alias: str, digest: str, sigalg: str) -> None:
            run(jarsigner, "-keystore", stores[alias], "-storepass", PASSWORD, "-digestalg", digest, "-sigalg", sigalg,
                "-signedjar", dest, src, alias)

        sha1 = os.path.join(HERE, "index-v1.jar")
        sign(unsigned, sha1, "repokey", "SHA1", "SHA1withRSA")
        sign(unsigned, os.path.join(HERE, "index-v1-sha256.jar"), "repokey", "SHA-256", "SHA256withRSA")
        sign(sha1, os.path.join(HERE, "index-v1-two-signers.jar"), "otherkey", "SHA-256", "SHA256withRSA")

        # Without signed attributes: jarsigner always adds them, openssl -noattr does not.
        key_pem, cert_pem = os.path.join(tmp, "key.pem"), os.path.join(tmp, "cert.pem")
        run("openssl", "pkcs12", "-in", store, "-passin", f"pass:{PASSWORD}", "-nodes", "-nocerts", "-out", key_pem)
        run("openssl", "pkcs12", "-in", store, "-passin", f"pass:{PASSWORD}", "-nokeys", "-clcerts", "-out", cert_pem)
        with zipfile.ZipFile(os.path.join(HERE, "index-v1-sha256.jar")) as z:
            names = z.namelist()
            sf_name = next(n for n in names if n.endswith(".SF"))
            parts = {n: z.read(n) for n in names}
        sf_path, rsa_path = os.path.join(tmp, "REPOKEY.SF"), os.path.join(tmp, "REPOKEY.RSA")
        with open(sf_path, "wb") as f:
            f.write(parts[sf_name])
        run("openssl", "smime", "-sign", "-binary", "-noattr", "-md", "sha256", "-outform", "DER",
            "-in", sf_path, "-signer", cert_pem, "-inkey", key_pem, "-out", rsa_path)
        with open(rsa_path, "rb") as f:
            block = f.read()
        with zipfile.ZipFile(os.path.join(HERE, "index-v1-noattr.jar"), "w", zipfile.ZIP_DEFLATED) as z:
            for name in names:
                z.writestr(name, block if name.endswith(".RSA") else parts[name])

        for alias in ("repokey", "otherkey"):
            der = subprocess.run([keytool, "-exportcert", "-keystore", stores[alias], "-storepass", PASSWORD, "-alias", alias],
                                 check=True, capture_output=True).stdout
            print(f"{alias}: {hashlib.sha256(der).hexdigest()}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
