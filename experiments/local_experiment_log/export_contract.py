"""Export unfilled measurement templates and an explicitly synthetic example."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.local_experiment_log.contract import CONFIG_SCHEMA, EVENT_SCHEMA, MANIFEST_SCHEMA, template
from experiments.local_experiment_log.canonical_bridge import accounting
from experiments.local_experiment_log.tests.canonical_fixtures import compatible_fixture


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.out_dir
    if root.exists() or root.is_symlink():
        parser.error("output directory must be new")
    canonical_schema = json.loads(accounting.SCHEMA_PATH.read_text())
    canonical_template = {key: None for key in canonical_schema["required"]}
    canonical_template.update(schemaVersion="sermon-workflow-accounting-v3", contractVersion=accounting.VERSION, missingReasons={})
    manifest, events, contexts = compatible_fixture()
    root.mkdir(parents=True)
    for name, value in {"event.schema.json": EVENT_SCHEMA, "config.schema.json": CONFIG_SCHEMA,
                        "manifest.schema.json": MANIFEST_SCHEMA, "event.template.json": template(),
                        "log-record.template.json": canonical_template,
                        "manifest.template.json": {"schema_version": "local.experiment.manifest.v1",
                            "experiment_id": None, "evidence_kind": None, "duration_mode": None,
                            "duration_seconds": 180, "layer_component_mapping": {},
                            "admission_design_reference": None, "artifact_return_reference": None},
                        "config.template.json": {key: None for key in CONFIG_SCHEMA["required"]}}.items():
        write(root / name, value)
    write(root / "example/manifest.json", manifest)
    write(root / "example/contexts.synthetic.json", contexts)
    (root / "example/events.synthetic.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False, allow_nan=False) + "\n" for e in events))
    print("Exported templates and synthetic example; no real execution")
    return 0


if __name__ == "__main__":
    sys.exit(main())
