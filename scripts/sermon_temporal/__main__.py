"""python -m scripts.sermon_temporal server|worker|client ..."""
import sys


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("server", "worker", "worker-service", "client"):
        raise SystemExit("Usage: python -m scripts.sermon_temporal {server|worker|worker-service|client} --help")
    if sys.argv[1] == "server":
        from .server import main as entry
    elif sys.argv[1] == "worker":
        from .worker import main as entry
    elif sys.argv[1] == "worker-service":
        from .worker_service import main as entry
    else:
        from .cli import main as entry
    entry(sys.argv[2:])


if __name__ == "__main__":
    main()
