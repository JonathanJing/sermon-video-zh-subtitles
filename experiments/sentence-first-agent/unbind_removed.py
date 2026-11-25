#!/usr/bin/env python3
"""On Spark: drop an auto-removed container id from one job of my exclusive session (user-approved 2026-10-22)."""
import datetime, fcntl, json, os, shutil, subprocess
from pathlib import Path
ROOT = Path.home() / ".local/state/tongxing-spark-exclusive"
SESSION, JOB = "sfa-podcast-20261022", "adc078f7051e4de4b5c96b5d7ab7a083"
CID = "4a6beebc53cfc5917baba58fbd8861d019efbd2dc4cb62ac9adfcbdfdaed8c29"
fd = os.open(ROOT / "owner.lock", os.O_RDWR | os.O_CREAT, 0o600)
fcntl.flock(fd, fcntl.LOCK_EX)
try:
    path = ROOT / "session.json"
    state = json.loads(path.read_text())
    assert state["sessionId"] == SESSION and state["status"] == "running", (state["sessionId"], state["status"])
    job = state["jobs"][JOB]
    assert job["status"] == "active" and job["containerIds"] == [CID], job
    # The container must really be gone and nothing of ours running.
    exists = subprocess.run(["docker", "inspect", CID], capture_output=True).returncode == 0
    assert not exists, "container still exists; not editing"
    running = subprocess.run(["docker", "ps", "-q", "--filter", f"label=tongxing.spark.session={SESSION}"], capture_output=True, text=True).stdout.split()
    assert not running, f"session containers still running: {running}"
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = ROOT / f"session.json.bak-{stamp}"
    shutil.copy2(path, backup)
    job["containerIds"] = []
    state["revision"] += 1
    state["updatedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    state["events"].append({"revision": state["revision"], "at": state["updatedAt"], "event": "manual_removed_container_unbind",
                            "jobId": JOB, "containerId": CID,
                            "reason": "container was started with --rm and auto-removed after exit 0 (tts exit zh-Hans 0 2026-10-22T05:31:30Z); every docker inspect of the bound id failed. User approved this edit in chat on 2026-10-22.",
                            "backup": backup.name})
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    print(json.dumps({"edited": True, "backup": str(backup), "revision": state["revision"]}))
finally:
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
