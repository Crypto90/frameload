#!/usr/bin/env bash
# Builds FramePort's FrameBridge adapter (libopenxr_loader_generic.so) with FrameLoad's patches.
# Run by .github/workflows/framebridge.yml; needs Linux x86_64 with python3, curl, patch.
# The FramePort release it patches is pinned in FRAMEPORT_VERSION; ORIGINAL_SHA256 is the arm64 adapter that
# release ships, which FrameLoad checks on the headset before it swaps in the patched build.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
version="$(cat "$here/FRAMEPORT_VERSION")"
out="${1:-$here/out}"
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

# The release's own adapter must be the one FrameLoad expects to replace.
have="$(sha256sum "$src/artifacts/arm64-v8a/libopenxr_loader_generic.so" | cut -d' ' -f1)"
want="$(cat "$here/ORIGINAL_SHA256")"
[[ "$have" == "$want" ]] || { echo "FramePort v${version}'s adapter is $have, expected $want" >&2; exit 1; }

for p in "$here"/*.patch; do
    echo "== applying $(basename "$p")"
    patch -d "$src" -p1 --forward < "$p"
done

(cd "$src" && python3 native/build.py --only adapter)

cp "$src/artifacts/arm64-v8a/libopenxr_loader_generic.so" "$out/libopenxr_loader_generic-arm64-v8a.so"
cp "$src/artifacts/armeabi-v7a/libopenxr_loader_generic.so" "$out/libopenxr_loader_generic-armeabi-v7a.so"
(cd "$out" && sha256sum libopenxr_loader_generic-*.so > SHA256SUMS && cat SHA256SUMS)
