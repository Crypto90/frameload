import subprocess
import os

rclone = "/Users/nicosprang/.local/share/frameload/bin/rclone"
password = "gL59VfgPxoHR"
res1 = subprocess.run([rclone, "obscure", password], capture_output=True, text=True)
obscured = res1.stdout.strip()

conf = "/Users/nicosprang/.local/share/frameload/data/.rclone/test.conf"
with open(conf, "w") as f:
    f.write(f"""[vrsrc]
type = webdav
url = https://go.srcdl1.xyz
vendor = other
user = 
pass = {obscured}
""")

env = os.environ.copy()
cmd2 = [
    rclone, "lsf", "vrsrc:/Quest Games/",
    "--config", conf,
    "--no-check-certificate",
    "--user-agent", "VR CyberDeck/1.2.1"
]
res2 = subprocess.run(cmd2, env=env, capture_output=True, text=True)
print("Result LSF:", res2.stdout[:200])
if res2.stderr: print("Error:", res2.stderr)
