"""tools/ops/review_gates.py and review_gate_server.py: gates on disk, and the service that accepts decisions."""
import http.client
import json
from pathlib import Path
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "ops"))
import review_gate_server as server_module  # noqa: E402
import review_gates  # noqa: E402

PRODUCTION = "20261128-sermon"
BINDINGS = {"anchorManifestJsonSha256": "ab" * 32, "sourceMediaSha256": "cd" * 32}
ROWS = {"summary": {"fileName": "x.mp4", "durationSeconds": 60.0, "window": {"start": 0.0, "end": 60.0}, "transcription": "t"},
        "rows": [{"id": "u0001", "start": 0.5, "end": 2.0, "seconds": 1.5, "english": "Hello.", "flags": [], "before": None,
                  "secondPass": None, "audio": "slices/u0001.wav"}]}


def schema(name):
    return json.loads((ROOT / "schemas" / f"sermon-review-{name}-v1.schema.json").read_text(encoding="utf-8"))


def decision(**changes):
    value = {"schemaVersion": "sermon-review-decision-v1", "gateId": "l1.english-review", "kind": "english", "production": PRODUCTION,
             "locale": None, "revision": 1, "bindings": dict(BINDINGS), "verdict": "approved",
             "checks": {"sourceIdentity": True, "window": True}, "payload": {"edits": {}}, "note": "",
             "idempotencyKey": "0123456789abcdef0123", "client": {"submittedAt": "2026-11-29T04:00:00Z", "userAgent": "test"}}
    value.update(changes)
    return value


@pytest.fixture
def store(tmp_path):
    store = review_gates.Store(tmp_path)
    store.write_production({"production": PRODUCTION, "episode": {"sunday": "2026-11-29", "title": None, "speaker": None},
                            "worker": {"lastSeenAt": "2026-11-29T03:00:00+00:00", "state": "在线", "stage": "s", "detail": "d"}})
    assets = tmp_path / "assets"
    (assets / "slices").mkdir(parents=True)
    (assets / "slices" / "u0001.wav").write_bytes(bytes(range(100)))
    (assets / "secret.txt").write_text("no")
    (tmp_path / "outside.wav").write_bytes(b"outside")
    store.open_gate(PRODUCTION, gate_id="l1.english-review", kind="english", title="英文表批准", bindings=dict(BINDINGS),
                    data=ROWS, assets_root=assets, summary="1 句")
    return store


@pytest.fixture
def service(store, tmp_path):
    called = []
    server = server_module.make_server(tmp_path, port=0, allowed_hosts={"mac.tailnet.ts.net"}, on_decision=called.append)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(method, path, body=None, headers=None, host="127.0.0.1"):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
        headers = {"Host": host, **(headers or {})}
        data = None
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            headers.setdefault("Content-Type", "application/json")
        connection.request(method, path, body=data, headers=headers)
        response = connection.getresponse()
        payload = response.read()
        connection.close()
        return response, payload

    yield request, called
    server.shutdown()
    server.server_close()


def test_descriptor_and_index_match_the_schemas_the_pages_use(store):
    jsonschema = pytest.importorskip("jsonschema")
    gate = store.descriptor(PRODUCTION, "l1.english-review", {"login": "a@b", "name": "A", "source": "tailscale"})
    jsonschema.validate(gate, schema("gate"))
    assert gate["labels"] == {"machineGenerated": True, "humanApproval": False}
    assert gate["assetsBase"] == f"files/{PRODUCTION}/l1.english-review/" and gate["lastDecision"] is None
    jsonschema.validate(store.index(PRODUCTION), schema("index"))


def test_a_decision_is_stored_once_and_the_same_key_returns_the_first_record(service, store):
    request, called = service
    response, payload = request("POST", "/api/decisions", decision(), {"Tailscale-User-Login": "me@example.com", "Tailscale-User-Name": "Me"})
    assert response.status == 202
    reply = json.loads(payload)
    assert reply["outcome"] == "queued" and reply["reviewer"] == "Me" and called == [PRODUCTION]
    files = list((store.gate_dir(PRODUCTION, "l1.english-review") / "decisions").glob("*.json"))
    assert len(files) == 1
    record = json.loads(files[0].read_text())
    assert record["reviewer"] == {"login": "me@example.com", "name": "Me", "source": "tailscale"}
    assert store.gate(PRODUCTION, "l1.english-review")["state"] == "submitted"
    again, payload = request("POST", "/api/decisions", decision())
    assert again.status == 202 and json.loads(payload)["decisionId"] == reply["decisionId"]
    other, payload = request("POST", "/api/decisions", decision(idempotencyKey="ffffffffffffffffffff"))
    assert other.status == 409 and json.loads(payload)["code"] == "not_open"
    assert len(list(files[0].parent.glob("*.json"))) == 1
    assert store.descriptor(PRODUCTION, "l1.english-review", {"login": None, "source": "local"})["lastDecision"]["outcome"] == "queued"


@pytest.mark.parametrize("change, status, code", [
    ({"revision": 2}, 409, "stale"),
    ({"bindings": {"anchorManifestJsonSha256": "00" * 32, "sourceMediaSha256": "cd" * 32}}, 409, "stale"),
    ({"checks": {"sourceIdentity": True, "window": False}}, 400, "invalid_decision"),
    ({"verdict": "ok"}, 400, "invalid_decision"),
    ({"kind": "track"}, 400, "invalid_decision"),
    ({"idempotencyKey": "short"}, 400, "invalid_decision"),
    ({"note": "x" * 5000}, 400, "invalid_decision"),
    ({"gateId": "l9.nothing"}, 404, "unknown_gate"),
    ({"production": "../etc"}, 404, "unknown_production"),
])
def test_a_decision_that_does_not_fit_the_open_revision_is_refused(service, store, change, status, code):
    request, called = service
    response, payload = request("POST", "/api/decisions", decision(**change))
    assert (response.status, json.loads(payload)["code"]) == (status, code)
    assert called == [] and store.gate(PRODUCTION, "l1.english-review")["state"] == "open"


def test_requests_from_another_site_or_in_another_format_are_refused(service):
    request, called = service
    assert request("POST", "/api/decisions", decision(), host="evil.example")[0].status == 403
    assert request("POST", "/api/decisions", decision(), {"Origin": "https://evil.example"})[0].status == 403
    assert request("POST", "/api/decisions", decision(), {"Origin": "https://mac.tailnet.ts.net:8444"}, host="mac.tailnet.ts.net:8444")[0].status == 202
    assert request("POST", "/api/decisions", b"x=1", {"Content-Type": "application/x-www-form-urlencoded"})[0].status == 415
    assert request("POST", "/api/decisions", b"{not json")[0].status == 400
    assert request("POST", "/api/other", decision())[0].status == 404
    assert request("GET", "/api/gates", host="evil.example")[0].status == 403


def test_only_listed_identities_may_decide_when_a_list_is_set(store, tmp_path):
    server = server_module.make_server(tmp_path, port=0, allowed_logins={"me@example.com"})
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        def post(login):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
            headers = {"Content-Type": "application/json", **({"Tailscale-User-Login": login} if login else {})}
            connection.request("POST", "/api/decisions", body=json.dumps(decision()).encode(), headers=headers)
            return connection.getresponse().status
        assert post("someone@else.com") == 403 and post(None) == 403 and post("me@example.com") == 202
    finally:
        server.shutdown()
        server.server_close()


def test_api_reads_and_the_viewer_identity(service):
    request, _ = service
    response, payload = request("GET", f"/api/gate?production={PRODUCTION}&gate=l1.english-review", headers={"Tailscale-User-Login": "me@example.com"})
    gate = json.loads(payload)
    assert response.status == 200 and gate["viewer"]["source"] == "tailscale" and gate["data"]["rows"][0]["id"] == "u0001"
    assert response.getheader("Cache-Control") == "no-store"
    local = json.loads(request("GET", f"/api/gate?production={PRODUCTION}&gate=l1.english-review")[1])["viewer"]
    assert local["source"] == "local" and local["login"].startswith("local:")
    index = json.loads(request("GET", "/api/gates")[1])                # newest production when none is named
    assert index["production"] == PRODUCTION and index["gates"][0]["state"] == "open"
    assert request("GET", "/api/gate?production=nope&gate=l1.english-review")[0].status == 404


def test_media_supports_range_and_stays_inside_the_gate_directory(service):
    request, _ = service
    base = f"/files/{PRODUCTION}/l1.english-review/"
    whole, body = request("GET", base + "slices/u0001.wav")
    assert (whole.status, whole.getheader("Accept-Ranges"), whole.getheader("Content-Type"), len(body)) == (200, "bytes", "audio/wav", 100)
    part, body = request("GET", base + "slices/u0001.wav", headers={"Range": "bytes=10-19"})
    assert (part.status, part.getheader("Content-Range"), body) == (206, "bytes 10-19/100", bytes(range(10, 20)))
    tail, body = request("GET", base + "slices/u0001.wav", headers={"Range": "bytes=-5"})
    assert (tail.status, tail.getheader("Content-Range"), body) == (206, "bytes 95-99/100", bytes(range(95, 100)))
    open_end, body = request("GET", base + "slices/u0001.wav", headers={"Range": "bytes=90-"})
    assert (open_end.status, len(body)) == (206, 10)
    beyond, _ = request("GET", base + "slices/u0001.wav", headers={"Range": "bytes=500-600"})
    assert (beyond.status, beyond.getheader("Content-Range")) == (416, "bytes */100")
    head, body = request("HEAD", base + "slices/u0001.wav")
    assert (head.status, head.getheader("Content-Length"), body) == (200, "100", b"")
    for path in ("../outside.wav", "..%2Foutside.wav", "secret.txt", "slices/missing.wav", "%2e%2e/%2e%2e/outside.wav"):
        assert request("GET", base + path)[0].status == 404, path


def test_static_pages_come_with_the_strict_csp_and_nothing_else_is_served(service):
    request, _ = service
    page, body = request("GET", "/")
    assert page.status == 200 and b"<title>" in body and page.getheader("Content-Type").startswith("text/html")
    csp = page.getheader("Content-Security-Policy")
    assert "default-src 'none'" in csp and "script-src 'self'" in csp and "'unsafe-inline'" not in csp
    assert page.getheader("X-Content-Type-Options") == "nosniff"
    module, _ = request("GET", "/gate.mjs")
    assert module.status == 200 and module.getheader("Content-Type").startswith("text/javascript")
    for path in ("/README.zh.md", "/../../AGENTS.md", "/%2e%2e/%2e%2e/AGENTS.md", "/nothing.html", "/demo/"):
        assert request("GET", path)[0].status == 404, path


def test_range_parsing():
    parse = server_module.parse_range
    assert parse(None, 10) is None and parse("items=0-1", 10) is None and parse("bytes=-", 10) is None
    assert parse("bytes=0-3", 10) == (0, 3) and parse("bytes=5-", 10) == (5, 9) and parse("bytes=-3", 10) == (7, 9)
    assert parse("bytes=8-99", 10) == (8, 9) and parse("bytes=10-", 10) == (-1, -1) and parse("bytes=5-2", 10) == (-1, -1)


def test_outcomes_move_the_gate_and_an_old_revision_cannot_touch_a_new_one(store):
    first = store.record_decision(decision(), {"login": "a", "name": "A", "source": "local"})
    assert [r["decisionId"] for r in store.pending(PRODUCTION)] == [first["decisionId"]]
    newer = {"anchorManifestJsonSha256": "ee" * 32, "sourceMediaSha256": "cd" * 32}
    gate = store.open_gate(PRODUCTION, gate_id="l1.english-review", kind="english", title="英文表批准", bindings=newer, data=ROWS)
    assert (gate["revision"], gate["state"]) == (2, "open")
    store.record_outcome(PRODUCTION, "l1.english-review", first["decisionId"], "rejected_stale", message="changed")
    assert store.gate(PRODUCTION, "l1.english-review")["state"] == "open", "the stale decision was about revision 1"
    assert store.pending(PRODUCTION) == [] and store.last_decision(PRODUCTION, "l1.english-review") is None
    second = store.record_decision(decision(revision=2, bindings=newer, idempotencyKey="1111111111111111aaaa"),
                                   {"login": "a", "name": "A", "source": "local"})
    store.record_outcome(PRODUCTION, "l1.english-review", second["decisionId"], "applied", receipt_sha256="12" * 32, next_stage="翻译")
    last = store.last_decision(PRODUCTION, "l1.english-review")
    assert store.gate(PRODUCTION, "l1.english-review")["state"] == "applied"
    assert (last["outcome"], last["receiptSha256"], last["nextStage"]) == ("applied", "12" * 32, "翻译")
    same = store.open_gate(PRODUCTION, gate_id="l1.english-review", kind="english", title="英文表批准", bindings=newer, data=ROWS)
    assert same["revision"] == 2 and same["state"] == "applied", "the same hashes do not reopen an approved gate"


def test_a_request_for_changes_is_applied_as_changes_requested(store):
    record = store.record_decision(decision(verdict="changes_requested", checks={"window": False}, note="改第 3 句"),
                                   {"login": "a", "name": "A", "source": "local"})
    store.record_outcome(PRODUCTION, "l1.english-review", record["decisionId"], "applied")
    assert store.gate(PRODUCTION, "l1.english-review")["state"] == "changes_requested"
    reopened = store.open_gate(PRODUCTION, gate_id="l1.english-review", kind="english", title="英文表批准", bindings=dict(BINDINGS), data=ROWS)
    assert (reopened["revision"], reopened["state"]) == (2, "open"), "after changes the same hashes still need a new review"


def test_the_service_refuses_to_listen_beyond_loopback():
    with pytest.raises(SystemExit):
        server_module.main(["serve", "--bind", "0.0.0.0", "--port", "0"])
