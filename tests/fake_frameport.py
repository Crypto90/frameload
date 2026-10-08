"""Stand-in for FramePort's command line in tests: same commands and output lines, no real porting."""
import json
import os
import sys
import zipfile

HOME = os.environ.get("FRAMEPORT_HOME", "")
STATE = os.path.join(HOME, "fake-state.json")


def state():
    try:
        with open(STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"tools": False, "games": {}}


def save(data):
    os.makedirs(HOME, exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(data, f)


def main(argv):
    data = state()
    if argv == ["--version"]:
        print("FramePort 9.9.9")
        return 0
    if argv == ["tools", "status"]:
        word = "installed" if data["tools"] else "missing"
        for name in ("java", "overport", "apksigner"):
            print(f"{name:10} {word:9} 1.0  /tools/{name}")
        print(f"{'revive':10} {'missing':9} -  ")
        return 0
    if argv == ["tools", "install"]:
        data["tools"] = True
        save(data)
        print("java       21  /tools/java")
        return 0
    if argv[:1] == ["scan"]:
        folder = argv[1]
        for name in os.listdir(folder):
            if name.endswith(".apk"):
                package = name[:-4]
                data["games"][package] = os.path.join(folder, name)
                print(f"{package:40} {'Test Game':34} {'suggested':11} heuristics")
        save(data)
        return 0
    if argv[:1] == ["build"]:
        package, outdir = argv[1], argv[argv.index("--outdir") + 1]
        source = data["games"].get(package)
        if not source or os.environ.get("FAKE_FRAMEPORT_FAIL"):
            print(f"{package}: FAILED overport: could not patch", file=sys.stderr)
            return 1
        result = os.path.join(outdir, f"{package}-frame.apk")
        with zipfile.ZipFile(source) as src, zipfile.ZipFile(result, "w") as dst:
            for item in src.infolist():
                if item.filename != "lib/arm64-v8a/libOVRPlugin.so":
                    dst.writestr(item, src.read(item.filename))
            if not os.environ.get("FAKE_FRAMEPORT_NO_ADAPTER"):
                dst.writestr("lib/arm64-v8a/libframe_settings.so", b"settings")
                dst.writestr("lib/arm64-v8a/libopenxr_loader_original.so", b"loader")
            dst.writestr("lib/arm64-v8a/libopenxr_loader.so", b"adapter")
        print("  step: overport")
        print(f"{package}: OK -> {result}")
        return 0
    print("unknown command", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
