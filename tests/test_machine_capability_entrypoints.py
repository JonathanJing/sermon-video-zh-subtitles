"""Older frozen capabilities cannot authorize machine waiver ingest or delivery."""
import json
from unittest import mock

import pytest

from scripts import sermon_unified_capabilities as capabilities
from scripts import sermon_unified_delivery as delivery
from scripts import sermon_unified_reviews as reviews
from scripts.sermon_unified import adapters, contracts, runtime


def old_capabilities():
    return {"schemaVersion": capabilities.VERSION, "snapshotBound": True,
            "targetSchemaVersions": capabilities.SCHEMAS}


def test_machine_review_ingest_rejects_v2_before_persisting(tmp_path):
    config = tmp_path / "review.json"
    config.write_text(json.dumps({"schemaVersion": "sermon-unified-review-inputs-v1", "inputs": {}}))
    receipt = tmp_path / "waiver.json"
    receipt.write_text('{"reviewKind": "machine_quality_waiver"}')
    step = {"id": "review", "adapter": "review.gate", "dependsOn": [], "reviewKind": "translation"}
    state = {"stateRevision": 1, "manifest": {"steps": [step], "source": {}, "transport": "canonical"},
             "steps": {"review": {}}, "reviews": {}}
    with mock.patch.object(runtime, "load", return_value=state), \
         mock.patch.object(contracts, "job_identity", return_value={}), \
         mock.patch.object(contracts, "digest", return_value="job"), \
         mock.patch.object(adapters, "inspect_step"), \
         mock.patch.object(adapters, "config_path", return_value=config), \
         mock.patch.object(contracts, "binding", return_value=tmp_path / "capabilities.json"), \
         mock.patch.object(reviews, "validate_review", return_value={"reviewKind": "machine_quality_waiver"}), \
         mock.patch.object(capabilities, "inspect", return_value=old_capabilities()), \
         mock.patch.object(runtime.jobs, "_persist") as persist:
        with pytest.raises(ValueError, match="consumer_machine_capabilities_required"):
            runtime.ingest_review(tmp_path, "run", "job", receipt, 1)
        persist.assert_not_called()
    assert state["reviews"] == {}


def test_machine_delivery_rejects_v2_before_source_or_release_preparation(tmp_path):
    step = {"adapter": "app.delivery", "stageId": "publish_endpoint"}
    with mock.patch.object(delivery, "inspect", return_value={"snapshotBound": True, "machineChecked": True}), \
         mock.patch.object(adapters, "config_path", return_value=tmp_path / "delivery.json"), \
         mock.patch.object(contracts, "binding", return_value=tmp_path / "capabilities.json"), \
         mock.patch.object(capabilities, "inspect", return_value=old_capabilities()):
        with pytest.raises(ValueError, match="consumer_machine_capabilities_required"):
            adapters.inspect_step({}, tmp_path, step)
