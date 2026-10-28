# FrameBridge patches

FrameLoad ports Quest games with [FramePort](https://github.com/spoopyghosty0/frameport) (GPL-3.0), whose FrameBridge
adapter (`libopenxr_loader_generic.so`) sits between a game and the Frame's OpenXR runtime. These patches fix games
that FramePort's own build does not run yet. FrameLoad ships no native code of its own; this folder is the complete
source of what it changes.

| Patch | What it fixes |
|---|---|
| `wait_balance.patch` | A game waits for a frame (`xrWaitFrame`) and never begins it, then waits again. Meta's runtime returns; SteamVR's blocks until the first frame is begun, which never happens when the waiting thread holds a lock the rest of the game needs. SWORDS of GARGANTUA (Unreal 4, OVRPlugin 1.89, GLES) stays on its loading screen forever: the render thread waits inside OVRPlugin's lock and the game thread waits for that lock in `ovrp_GetControllerState4`. The second wait now first gives the game 500 ms to begin the waited frame, then begins and ends it with no layers itself. `wait_balance=0` in the game's FrameBridge settings turns it off. |

## Staying current

`.github/workflows/framebridge.yml` runs every day: when FramePort has published a release that has no build here
yet, it downloads that release, checks its adapters against FramePort's own `SHA256SUMS`, applies the patches, runs
FramePort's `native/build.py --only adapter` and publishes a prerelease `framebridge-<FramePort version>-p<revision>`
(`PATCH_REVISION`) with the patched adapters, their `SHA256SUMS` and the release's `ORIGINAL_SHA256SUMS`. No FrameLoad
release is needed for a new FramePort version: on the headset `frameload/installer/framebridge_patch.py` looks up
the newest build for the FramePort it runs (cached 6 hours) and verifies every download against that build's sums.

On the headset FrameLoad replaces the adapter inside its own FramePort install only while that install's adapter is
byte for byte the release's (`ORIGINAL_SHA256SUMS`), keeps the original beside it, and puts it back when it has no
build to vouch for a patched file. A FramePort with no build yet ports exactly as before. Games that never showed a
picture are ported again once with each new build (`porting.port_with_patch`).

When FramePort changes the code a patch touches, the daily run fails and GitHub mails the repository owner: rebase
the patch, raise `PATCH_REVISION` and push a tag `framebridge-<version>-p<revision>`. `FRAMEPORT_VERSION` is the
version the patches were written for.
