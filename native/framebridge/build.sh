#!/usr/bin/env bash
# Builds FramePort's FrameBridge adapter (libopenxr_loader_generic.so) with FrameLoad's patches.
#   build.sh <out dir> [FramePort version]     (default: FRAMEPORT_VERSION)
# Run by .github/workflows/framebridge.yml on Linux x86_64 (python3, curl, patch). Writes to <out dir>:
#   libopenxr_loader_generic-<abi>.so   the patched adapters
#   SHA256SUMS                          their checksums
#   ORIGINAL_SHA256SUMS                 the adapters the FramePort release ships (what FrameLoad may replace)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
out="${1:-$here/out}"
version="${2:-$(cat "$here/FRAMEPORT_VERSION")}"
work="$(mktemp -d)"
mkdir -p "$out"

curl -fsSL "https://codeload.github.com/spoopyghosty0/frameport/tar.gz/refs/tags/v${version}" -o "$work/fp.tgz"
tar xzf "$work/fp.tgz" -C "$work"
src="$work/frameport-${version}"
# The NDK, OpenXR headers and shader tools FramePort's build downloads (about 1 GB): kept between CI runs.
if [[ -n "${FRAMEBRIDGE_CACHE:-}" ]]; then
    mkdir -p "$FRAMEBRIDGE_CACHE"
    ln -s "$FRAMEBRIDGE_CACHE" "$src/native/.cache"
fi

# The release's own adapters, as its SHA256SUMS lists them: what FrameLoad may swap on the headset.
: > "$out/ORIGINAL_SHA256SUMS"
for abi in arm64-v8a armeabi-v7a; do
    have="$(sha256sum "$src/artifacts/$abi/libopenxr_loader_generic.so" | cut -d' ' -f1)"
    listed="$(awk -v f="./$abi/libopenxr_loader_generic.so" '$2 == f {print $1}' "$src/artifacts/SHA256SUMS")"
    [[ "$have" == "$listed" ]] || { echo "FramePort v${version}: $abi adapter $have is not the listed $listed" >&2; exit 1; }
    echo "$have  libopenxr_loader_generic-$abi.so" >> "$out/ORIGINAL_SHA256SUMS"
done

for p in "$here"/*.patch; do
    echo "== applying $(basename "$p")"
    patch -d "$src" -p1 --forward --no-backup-if-mismatch < "$p"
done

build() { (cd "$src" && python3 native/build.py --only adapter); }
# build.py unpacks the NDK with Python's zipfile, which drops the executable bits of its shader tools (glslc):
# a first run fails there, the second runs with them executable.
build || { chmod -R +x "$src"/native/.cache/ndk-*/shader-tools "$src"/native/.cache/ndk-*/toolchains/llvm/prebuilt/*/bin
           build; }

cp "$src/artifacts/arm64-v8a/libopenxr_loader_generic.so" "$out/libopenxr_loader_generic-arm64-v8a.so"
cp "$src/artifacts/armeabi-v7a/libopenxr_loader_generic.so" "$out/libopenxr_loader_generic-armeabi-v7a.so"
(cd "$out" && sha256sum libopenxr_loader_generic-*.so > SHA256SUMS && cat SHA256SUMS ORIGINAL_SHA256SUMS)
