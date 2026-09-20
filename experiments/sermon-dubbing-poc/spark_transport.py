"""SSH/SCP through the Mac mini that owns the Spark SSH credentials."""
import os
from pathlib import Path
import shlex
import uuid


def bridge():
    return os.environ.get("SERMON_SPARK_BRIDGE", "jonyopenclaw@100.73.116.52")


def mini_ssh():
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "HostKeyAlias=" + os.environ.get("SERMON_SPARK_BRIDGE_ALIAS", "jonys-mac-mini.local"), bridge()]


def dispatch(argv, runner, **kwargs):
    if not bridge() or argv[0] not in ("ssh", "scp"):
        return runner(argv, **kwargs)
    if argv[0] == "ssh":
        return runner([*mini_ssh(), shlex.join(argv)], **kwargs)
    # Runner's SCP invocations use a fixed option prefix and ordinary file paths.
    i = 1
    while i < len(argv) and argv[i].startswith("-"):
        i += 2 if argv[i] == "-o" else 1
    options, files = argv[1:i], argv[i:]
    sources, destination = files[:-1], files[-1]
    tmp = "/tmp/sermon-spark-transfer-" + uuid.uuid4().hex
    mini_options = [*options, "-o", "HostKeyAlias=" + os.environ.get("SERMON_SPARK_BRIDGE_ALIAS", "jonys-mac-mini.local")]
    runner([*mini_ssh(), "mkdir -m 700 " + shlex.quote(tmp)], check=True)
    try:
        if ":" in destination:
            runner(["scp", *mini_options, *sources, bridge() + ":" + tmp + "/"], **kwargs)
            staged = [tmp + "/" + Path(source).name for source in sources]
            return runner([*mini_ssh(), shlex.join(["scp", *options, *staged, destination])], **kwargs)
        if len(sources) != 1 or ":" not in sources[0]:
            raise ValueError("Unsupported Spark transfer")
        runner([*mini_ssh(), shlex.join(["scp", *options, sources[0], tmp + "/"])], **kwargs)
        name = Path(sources[0].split(":", 1)[1]).name
        return runner(["scp", *mini_options, bridge() + ":" + tmp + "/" + name, destination], **kwargs)
    finally:
        runner([*mini_ssh(), "rm -rf -- " + shlex.quote(tmp)], check=False)
