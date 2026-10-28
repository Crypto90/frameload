# FrameBridge patches

FrameLoad ports Quest games with [FramePort](https://github.com/spoopyghosty0/frameport) (GPL-3.0), whose FrameBridge
adapter (`libopenxr_loader_generic.so`) sits between a game and the Frame's OpenXR runtime. These patches fix games
that FramePort's own build does not run yet. FrameLoad ships no native code of its own; this folder is the complete
source of what it changes.

| Patch | What it fixes |
|---|---|
| `wait_balance.patch` | A game waits for a frame (`xrWaitFrame`) and never begins it, then waits again. Meta's runtime returns; SteamVR's blocks until the first frame is begun, which never happens when the waiting thread holds a lock the rest of the game needs. SWORDS of GARGANTUA (Unreal 4, OVRPlugin 1.89, GLES) stays on its loading screen forever: the render thread waits inside OVRPlugin's lock and the game thread waits for that lock in `ovrp_GetControllerState4`. The second wait now first gives the game 500 ms to begin the waited frame, then begins and ends it with no layers itself. `wait_balance=0` in the game's FrameBridge settings turns it off. |

`FRAMEPORT_VERSION` pins the FramePort release the patches apply to and `ORIGINAL_SHA256` is the arm64 adapter that
release ships. `build.sh` downloads that release, checks the adapter, applies the patches and runs FramePort's own
`native/build.py --only adapter`. Pushing a tag `framebridge-<FramePort version>-p<n>` builds and publishes the
result (`.github/workflows/framebridge.yml`); `frameload/installer/framebridge_patch.py` downloads it by that tag.

On the headset FrameLoad replaces the adapter inside its own FramePort install only while that install's adapter is
byte for byte the release's (`ORIGINAL_SHA256`), keeps the original beside it, and puts it back as soon as FramePort
updates. A FramePort it has no patched build for ports exactly as before.

For a new FramePort release: bump `FRAMEPORT_VERSION` and `ORIGINAL_SHA256`, rebase the patches, push a new tag and
add its checksums to `framebridge_patch.py`.
