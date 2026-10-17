"""Transition facade: the implementation lives in tongxing_production.delivery.publication.

Importing this path names that module object, so attribute patches apply to both; running it
dispatches the command entry in tools/ops/guarded_hosting_publish.py (L4 D8).
``python scripts/guarded_hosting_publish.py`` and ``python -m scripts.guarded_hosting_publish`` still run the command.
Remove once no caller imports or runs the old path.
"""
from pathlib import Path
import sys

try:
    from scripts import tongxing_host  # noqa: F401  binds the production package ports
except ModuleNotFoundError:  # run directly, or imported by bare name, from scripts/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import tongxing_host  # noqa: F401
from tongxing_production.delivery import publication as _implementation  # noqa: E402

if __name__ == "__main__":
    # Only the command entry lives in tools/ops; importing this path never needs tools/.
    from tools.ops import guarded_hosting_publish as _command  # noqa: E402
    raise SystemExit(_command.main())
sys.modules[__name__] = _implementation
