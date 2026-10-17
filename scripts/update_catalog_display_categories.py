"""Compatibility entry point for the offline catalog category updater."""
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.ops import update_catalog_display_categories as _implementation

# The existing contract test loads this file with spec_from_file_location, which
# does not replace its module object when sys.modules is rebound below.
from tools.ops.update_catalog_display_categories import (  # noqa: F401
    main, parse_json, read_json, update_categories, validate_catalog, write_new,
)

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
