"""Explicit worker profiles; production execution is disabled unless requested."""
from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta
from pathlib import Path
import signal

from temporalio.client import Client
from temporalio.worker import Worker

from .activities import Activities
from .contracts import QUEUE_PREFIX
from .local_io import PROJECT_PYTHON, TEMPORAL_ROOT
from .workflows import SaturdayWorkflow


def local_address(address: str) -> str:
    host, port = address.rsplit(":", 1)
    if host not in ("127.0.0.1", "localhost") or not 1024 <= int(port) <= 65535:
        raise ValueError("This local deployment accepts loopback Temporal endpoints only")
    return address


async def serve(args):
    if args.profile == "fixture" and args.allow_production_execute:
        raise ValueError("A fixture worker can never enable production execution")
    client = await Client.connect(local_address(args.address), namespace=args.namespace)
    activities = Activities(profile=args.profile, state_root=args.state_root,
                            allow_production_execute=args.allow_production_execute,
                            project_python=args.project_python)
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stopped.set)
    async with Worker(client, task_queue=QUEUE_PREFIX + args.profile, workflows=[SaturdayWorkflow],
        activities=[activities.inspect, activities.execute], max_concurrent_activities=2,
        graceful_shutdown_timeout=timedelta(seconds=3),
        max_heartbeat_throttle_interval=timedelta(seconds=1),
        default_heartbeat_throttle_interval=timedelta(seconds=1)):
        print(f"Worker ready: profile={args.profile}, queue={QUEUE_PREFIX + args.profile}, production_execute={args.allow_production_execute}", flush=True)
        await stopped.wait()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:17233")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--profile", choices=("fixture", "production"), required=True)
    parser.add_argument("--state-root", type=Path, default=TEMPORAL_ROOT / "worker-state")
    parser.add_argument("--project-python", type=Path, default=PROJECT_PYTHON)
    parser.add_argument("--allow-production-execute", action="store_true")
    asyncio.run(serve(parser.parse_args(argv)))


if __name__ == "__main__":
    main()
