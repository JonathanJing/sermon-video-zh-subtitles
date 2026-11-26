"""apps/review-web: the human review pages (static checks, no browser)."""
import json
from pathlib import Path
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "review-web"
sys.path.insert(0, str(ROOT / "tools" / "ops"))
import production_notices as notices  # noqa: E402

GATE_KINDS = ["decisions", "english", "speakers", "track", "study", "publish", "confirm"]
PAGES = ["index", *GATE_KINDS]


def schema(name):
    return json.loads((ROOT / "schemas" / f"sermon-review-{name}-v1.schema.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("page", PAGES)
def test_page_obeys_the_strict_csp(page):
    html = (WEB / f"{page}.html").read_text(encoding="utf-8")
    assert not re.search(r"<style\b", html) and not re.search(r"\sstyle\s*=", html), "no inline styles"
    assert not re.search(r"\son[a-z]+\s*=", html), "no inline event handlers"
    assert "javascript:" not in html
    sources = re.findall(r"<script[^>]*\bsrc=\"([^\"]+)\"", html)
    assert sources == ["theme.js", f"{page}.mjs"], "only the blocking theme script and the page module"
    assert len(re.findall(r"<script\b", html)) == 2, "no inline script"
    assert re.findall(r"<link[^>]*href=\"([^\"]+)\"", html) == ["review.css"]
    assert not re.search(r"(?:src|href)=\"(?:https?:)?//", html), "everything is self-hosted"
    assert '<html lang="zh-Hans" data-theme="dark">' in html and 'name="robots" content="noindex"' in html


@pytest.mark.parametrize("kind", GATE_KINDS)
def test_gate_page_has_the_decision_bar_and_its_checks(kind):
    html = (WEB / f"{kind}.html").read_text(encoding="utf-8")
    assert f'<body data-kind="{kind}">' in html
    for element in ("label-strip", "bindings", "note", "result", "actions", "hint", "approve",
                    "request-changes", "confirm-dialog", "confirm-summary", "confirm-send", "confirm-cancel", "submit-error"):
        assert f'id="{element}"' in html, element
    names = re.findall(r'data-(?:check|affirm)="([A-Za-z]+)"', html)
    assert names and len(names) == len(set(names))
    if kind == "english":   # approving the English table is one action; nothing has to be ticked first
        assert 'type="checkbox"' not in html and len(re.findall(r'data-affirm="', html)) == 5
        assert "按默认通过" in html
    else:
        assert f'id="checks"' in html and re.findall(r'data-check="', html)
    module = (WEB / f"{kind}.mjs").read_text(encoding="utf-8")
    assert f'loadGate("{kind}")' in module and "setupDecision(gate" in module
    assert "gate.labels.rehearsal" in (WEB / "gate.mjs").read_text(encoding="utf-8"), "a rehearsal is labelled on every page"


def test_modules_never_build_html_from_strings():
    for module in WEB.glob("*.mjs"):
        text = module.read_text(encoding="utf-8")
        for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            assert banned not in text, f"{module.name}: {banned}"
    assert 'setAttribute("style"' not in (WEB / "gate.mjs").read_text(encoding="utf-8")


@pytest.mark.parametrize("kind", GATE_KINDS)
def test_demo_gate_matches_the_schema(kind):
    jsonschema = pytest.importorskip("jsonschema")
    gate = json.loads((WEB / "demo" / f"{kind}.json").read_text(encoding="utf-8"))
    jsonschema.validate(gate, schema("gate"))
    assert gate["kind"] == kind and gate["state"] == "open"
    assert gate["labels"] == {"machineGenerated": True, "humanApproval": False}, "a page shows machine output until a receipt exists"
    assert gate["viewer"]["source"] == "demo"


def test_demo_index_matches_the_schema_and_links_every_kind():
    jsonschema = pytest.importorskip("jsonschema")
    index = json.loads((WEB / "demo" / "index.json").read_text(encoding="utf-8"))
    jsonschema.validate(index, schema("index"))
    assert {gate["kind"] for gate in index["gates"]} == set(GATE_KINDS)
    pages = dict(re.findall(r"(\w+): \"(\w+\.html)\"", (WEB / "index.mjs").read_text(encoding="utf-8")))
    assert pages == {kind: f"{kind}.html" for kind in GATE_KINDS}


def test_decision_schema_binds_revision_and_hashes_and_wants_every_check_for_an_approval():
    jsonschema = pytest.importorskip("jsonschema")
    decision = {"schemaVersion": "sermon-review-decision-v1", "gateId": "l1.english-review", "kind": "english",
                "production": "demo-20261129-sample", "locale": None, "revision": 1, "bindings": {"anchorManifestJsonSha256": "ab" * 32},
                "verdict": "approved", "checks": {"sourceIdentity": True, "window": True}, "payload": {}, "note": "",
                "idempotencyKey": "0123456789abcdef0123", "client": {"submittedAt": "2026-11-29T04:00:00Z", "userAgent": "test"}}
    jsonschema.validate(decision, schema("decision"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**decision, "checks": {"sourceIdentity": True, "window": False}}, schema("decision"))
    jsonschema.validate({**decision, "verdict": "changes_requested", "checks": {"window": False}}, schema("decision"))
    for missing in ("revision", "bindings", "idempotencyKey"):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({k: v for k, v in decision.items() if k != missing}, schema("decision"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**decision, "bindings": {}}, schema("decision"))


def test_every_gate_kind_has_a_page_a_notice_and_a_schema_entry():
    assert sorted(notices.GATES) == sorted(GATE_KINDS) == sorted(schema("gate")["properties"]["kind"]["enum"])
    for kind, gate in notices.GATES.items():
        assert (WEB / gate["page"]).is_file() and gate["page"] == f"{kind}.html"


def test_demo_data_is_synthetic():
    text = "".join(path.read_text(encoding="utf-8") for path in (WEB / "demo").glob("*.json"))
    assert "Mariners" not in text and "drive.google.com" not in text and "ts.net" not in text
    assert "example.invalid" in text
