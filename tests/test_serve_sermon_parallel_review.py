import http.client
import importlib.util
from pathlib import Path
import sys
import tempfile
import threading
import unittest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "serve_sermon_parallel_review.py"
)
SPEC = importlib.util.spec_from_file_location(
    "serve_sermon_parallel_review", SCRIPT_PATH
)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class ServeSermonParallelReviewTest(unittest.TestCase):
    def make_item(self, *, boundary_approved=True):
        item = {
            "schemaVersion": mod.review_export.REVIEW_SCHEMA_VERSION,
            "reviewItemId": "abcdefghijk_seg_0001",
            "sermonId": "abcdefghijk",
            "segmentId": "abcdefghijk_seg_0001",
            "split": "poc",
            "priority": "normal",
            "issues": [mod.quality.GENERIC_NORMAL_ISSUE],
            "source": {
                "captionKind": "youtube_automatic",
                "reviewStatus": "unreviewed_raw",
                "manifestSha256": "a" * 64,
                "cuesSha256": "b" * 64,
                "textSha256": mod.corpus.sha256_bytes(b"Hello"),
                "cueIds": ["cue_1"],
                "startMs": 5000,
                "endMs": 9000,
                "english": "Hello",
            },
            "candidate": {
                "chinese": "你好",
                "chineseSha256": mod.corpus.sha256_bytes("你好".encode()),
                "contentType": "sermon",
                "scriptureRefs": [],
                "scriptureAlignments": [],
                "properNouns": [],
                "modelFlags": [],
                "modelNotes": [],
                "teacher": {
                    "provider": "openai",
                    "model": "gpt-5.6-sol",
                    "promptVersions": ["v1"],
                    "provenance": "gpt_isolated_nontrainable",
                },
                "modelReviewStatus": "model_reviewed_requires_human",
            },
            "boundary": {
                "status": (
                    "approved_human_boundary"
                    if boundary_approved
                    else "model_candidate_requires_human_review"
                ),
                "contentScope": "sermon_only",
                "approvedByHuman": boundary_approved,
                "startCueId": "cue_1",
                "endCueId": "cue_1",
                "boundarySha256": "c" * 64,
            },
            "reviewStatus": "pending_human",
            "trainingEligibility": "blocked",
        }
        item["reviewPayloadSha256"] = mod.review_export.review_payload_sha256(item)
        return item

    def make_store(self, temp: Path, *, boundary_approved=True):
        review_root = temp / "review"
        mod.corpus.write_jsonl(
            review_root / "review-items.all.jsonl",
            [self.make_item(boundary_approved=boundary_approved)],
        )
        return mod.ReviewStore(
            review_root=review_root,
            decisions_path=review_root / "human-decisions.jsonl",
            history_root=review_root / "decision-history",
        )

    def submitted(self):
        return {
            "status": "approved",
            "reviewer": "Reviewer",
            "reviewerRole": "bilingual_reviewer",
            "audioChecked": True,
            "englishDecision": "keep",
            "approvedEnglish": "Hello",
            "chineseDecision": "keep",
            "approvedChinese": "你好",
            "scriptureChecked": True,
            "properNounsChecked": True,
            "numbersChecked": True,
            "materialErrorTypes": [],
            "adjudicationComplete": True,
            "notes": "checked",
        }

    def test_store_saves_atomically_with_history_and_conflict_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            store = self.make_store(temp)
            self.assertEqual(store.summary()["status"], "content_review_ready")
            first = store.save_decision(
                item_id="abcdefghijk_seg_0001",
                submitted=self.submitted(),
                expected_decision_sha256=None,
            )
            self.assertEqual(first["summary"]["completed"], 1)
            self.assertEqual(
                mod.corpus.read_jsonl(store.decisions_path)[0]["status"], "approved"
            )
            self.assertEqual(len(list(store.history_root.rglob("*.json"))), 1)

            changed = self.submitted()
            changed["notes"] = "second review receipt"
            second = store.save_decision(
                item_id="abcdefghijk_seg_0001",
                submitted=changed,
                expected_decision_sha256=first["decisionSha256"],
            )
            self.assertNotEqual(first["decisionSha256"], second["decisionSha256"])
            self.assertEqual(len(list(store.history_root.rglob("*.json"))), 2)
            with self.assertRaises(mod.DecisionConflict):
                store.save_decision(
                    item_id="abcdefghijk_seg_0001",
                    submitted=changed,
                    expected_decision_sha256=first["decisionSha256"],
                )

    def test_store_blocks_content_write_until_boundary_is_approved(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory), boundary_approved=False)
            self.assertEqual(store.summary()["unapprovedBoundaryItems"], 1)
            with self.assertRaises(mod.BoundaryNotApproved):
                store.save_decision(
                    item_id="abcdefghijk_seg_0001",
                    submitted=self.submitted(),
                    expected_decision_sha256=None,
                )
            self.assertFalse(store.decisions_path.exists())

    def test_html_uses_nonce_and_does_not_embed_review_content(self):
        html = mod.render_html(read_only=True, nonce="nonce-value")
        self.assertIn('nonce="nonce-value"', html)
        self.assertIn("const READ_ONLY = true", html)
        self.assertNotIn("abcdefghijk_seg_0001", html)

    def test_loopback_api_requires_cookie_and_read_only_rejects_write(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            token = "test-session-token"
            server = mod.ThreadingHTTPServer(
                ("127.0.0.1", 0),
                mod.make_handler(store=store, token=token, read_only=True),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_address[1]
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            try:
                connection.request("GET", "/api/summary")
                self.assertEqual(connection.getresponse().status, 401)
                connection.request("GET", f"/?token={token}")
                response = connection.getresponse()
                self.assertEqual(response.status, 302)
                cookie = response.getheader("Set-Cookie").split(";", 1)[0]
                response.read()
                connection.request("GET", "/api/summary", headers={"Cookie": cookie})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertIn(b'"total": 1', response.read())
                connection.request(
                    "POST",
                    "/api/items/abcdefghijk_seg_0001/decision",
                    body=b"{}",
                    headers={
                        "Cookie": cookie,
                        "Content-Type": "application/json",
                        "Content-Length": "2",
                    },
                )
                self.assertEqual(connection.getresponse().status, 403)
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
