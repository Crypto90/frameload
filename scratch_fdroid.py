import urllib.request, zipfile, json, io

url = "https://f-droid.org/repo/index-v1.jar"
try:
    req = urllib.request.Request(url, headers={"User-Agent": "FrameLoad/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = resp.read()
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            with z.open("index-v1.json") as f:
                index = json.load(f)
                apps = index.get("apps", [])
                packages = index.get("packages", {})
                
                app = apps[0]
                pkg = app.get("packageName")
                pkgs = packages.get(pkg, [])
                
                print("App Keys:", app.keys())
                print("Name:", app.get("localized", {}).get("en-US", {}).get("name", app.get("name")))
                if pkgs:
                    print("Package Keys:", pkgs[0].keys())
                    print("Apk Name:", pkgs[0].get("apkName"))
except Exception as e:
    print("Error:", e)
