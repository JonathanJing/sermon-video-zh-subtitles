"""The spoken condensation driver: Codex condenser identity, record/brief writing, resume and refusals."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import run_machine_qc_clip_test as clip
from scripts import run_spoken_condensation as driver
from scripts import sermon_codex_transport as codex
from scripts import spoken_condensation as condensation
from tests import auto_qc_fixtures as fixtures
from tests import test_spoken_condensation as cases

LOCALE = cases.LOCALE


class ScriptedCondenser(cases.FakeCondenser):
    """Answers like the real condenser, cached per request, with an identity a record can carry."""

    identity = {"backend": "codex_cli_chatgpt", "model": codex.TEXT_MODEL, "modelRevision": "codex-cli 9.9.9",
                "cacheNamespace": driver.CACHE_NAMESPACE, "settings": {"reasoningEffort": "high"}}

    def __init__(self, *outputs, uncertain=()):
        super().__init__(*outputs)
        self.pending = list(uncertain)

        self.cache = {}

    def __call__(self, role, system, user, schema):
        key = (role, system, user)
        if key not in self.cache:
            self.cache[key] = super().__call__(role, system, user, schema)
        return self.cache[key]

    def uncertain(self):
        return self.pending


def full_candidate():
    candidate = cases.candidate()
    candidate["translationPolicySha256"] = cases.sha(fixtures.policy(LOCALE))
    return candidate


class SpokenCondensationDriverTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.inputs = {}
        candidate = full_candidate()
        for name, value in (("candidate", candidate), ("budget", cases.budget(candidate)),
                            ("anchor", cases.anchor()), ("policy", fixtures.policy(LOCALE))):
            path = self.root / "inputs" / f"{name}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            self.inputs[name] = path

    def main(self, condenser=None, *extra):
        args = [arg for name, path in self.inputs.items() for arg in (f"--{name}", str(path))]
        with patch.object(driver, "codex_condenser", lambda cache: condenser):
            return driver.main([*args, "--out", str(self.root / "out"), *extra])

    def summary(self, fake=False):
        return json.loads((self.root / "out" / ("fake-plumbing" if fake else "") / "summary.json")
                          .read_text(encoding="utf-8"))

    def test_record_and_brief_are_written_once_and_resumed(self):
        condenser = ScriptedCondenser(cases.answer())
        self.assertEqual(self.main(condenser), 0)
        row = self.summary()
        self.assertEqual((row["status"], row["condensedGroupIds"], row["modelCalls"]), ("brief_ready", ["g2"], 1))
        record = json.loads(Path(row["record"]).read_text(encoding="utf-8"))
        brief = json.loads(Path(row["revisionBrief"]).read_text(encoding="utf-8"))
        self.assertEqual(record["condenserIdentity"], ScriptedCondenser.identity)
        self.assertEqual((record["humanApproval"], record["mutatesFullCandidate"]), (False, False))
        self.assertEqual(brief, condensation.revision_brief(record, full_candidate()))
        self.assertTrue(clip.binding_path(Path(row["record"])).exists())
        # A rerun reuses the record without a model call and keeps the same files.
        again = ScriptedCondenser()
        self.assertEqual(self.main(again), 0)
        self.assertEqual(again.calls, [])
        self.assertTrue(self.summary()["recordReused"])
        self.assertEqual(sorted(p.name for p in (self.root / "out").glob("*.json") if "inputs" not in p.name),
                         sorted(["summary.json", Path(row["record"]).name, Path(row["revisionBrief"]).name]))

    def test_an_edited_record_is_never_replaced(self):
        self.assertEqual(self.main(ScriptedCondenser(cases.answer())), 0)
        path = Path(self.summary()["record"])
        path.write_text(path.read_text(encoding="utf-8").replace("filler", "aside"), encoding="utf-8")
        edited = path.read_text(encoding="utf-8")
        self.assertEqual(self.main(ScriptedCondenser(cases.answer())), 1)
        self.assertIn("changed after it was written", self.summary()["reason"])
        self.assertEqual(path.read_text(encoding="utf-8"), edited)

    def test_failed_groups_keep_the_full_text_and_are_reported(self):
        empty = {"translationGroupId": "g2", "spokenText": "", "omissions": []}
        condenser = ScriptedCondenser(empty, empty)
        self.assertEqual(self.main(condenser), 1)
        row = self.summary()
        self.assertEqual((row["status"], row["failedGroupIds"]), ("no_group_condensed", ["g2"]))
        self.assertNotIn("revisionBrief", row)

    def test_unknown_outcomes_block_new_dispatch(self):
        condenser = ScriptedCondenser(cases.answer(), uncertain=["abc"])
        self.assertEqual(self.main(condenser), 1)
        self.assertEqual((self.summary()["status"], condenser.calls), ("blocked_unknown_outcome", []))

    def test_the_candidates_own_policy_is_required(self):
        self.inputs["policy"].write_text(json.dumps({"other": True}), encoding="utf-8")
        condenser = ScriptedCondenser(cases.answer())
        self.assertEqual(self.main(condenser), 1)
        self.assertIn("frozen translation policy", self.summary()["reason"])
        self.assertEqual(condenser.calls, [])

    def test_fake_backend_writes_only_under_fake_plumbing(self):
        self.assertEqual(driver.main([arg for name, path in self.inputs.items() for arg in (f"--{name}", str(path))]
                                     + ["--out", str(self.root / "out"), "--backend", "fake"]), 0)
        row = self.summary(fake=True)
        self.assertEqual(row["status"], "brief_ready", row.get("reason"))
        record = json.loads(Path(row["record"]).read_text(encoding="utf-8"))
        self.assertTrue(record["condenserIdentity"]["backend"].startswith("fake"))
        self.assertEqual(record["groups"][0]["spokenText"], cases.SPOKEN)
        self.assertFalse((self.root / "out/summary.json").exists())
        with self.assertRaises(SystemExit):
            driver.main([arg for name, path in self.inputs.items() for arg in (f"--{name}", str(path))]
                        + ["--out", str(self.root / "out"), "--backend", "fake", "--state-dir", str(self.root)])

    def test_codex_condenser_uses_sol_high_with_its_own_cache(self):
        seen = []

        def fake_call(prompt, **options):
            seen.append(options)
            return cases.answer()

        cli = self.root / "bin/codex"
        cli.parent.mkdir()
        cli.write_bytes(b"cli")
        with patch.dict(clip.os.environ, {"SERMON_CODEX_CLI": str(cli)}), \
                patch.object(clip.subprocess, "check_output", return_value="codex-cli 9.9.9\n"), \
                patch.object(codex, "call_json", side_effect=fake_call):
            condenser = driver.codex_condenser(self.root / "calls")
            judge = clip.CodexJudge(self.root / "calls")
            record = condensation.condense(cases.anchor(), full_candidate(), cases.budget(full_candidate()),
                                           call=condenser, identity=condenser.identity,
                                           policy=fixtures.policy(LOCALE))
        self.assertEqual(record["status"], "condensed")
        self.assertEqual([(o["model"], o["reasoning"]) for o in seen], [(codex.TEXT_MODEL, "high")])
        self.assertEqual(seen[0]["timeout_seconds"], driver.TIMEOUT_SECONDS)
        self.assertEqual((condenser.identity["settings"]["reasoningEffort"], condenser.identity["cacheNamespace"]),
                         ("high", driver.CACHE_NAMESPACE))
        self.assertEqual(condensation.condenser_identity(condenser.identity)["identity"], condenser.identity)
        # The back-translation judge keeps its own identity, so the two never share cached calls.
        self.assertEqual((judge.identity["settings"]["reasoningEffort"], judge.identity["cacheNamespace"]),
                         ("medium", clip.CACHE_NAMESPACE))
        request = ("condenser", "sys", "user", {})
        self.assertNotEqual(condenser.key(*request), judge.key(*request))


if __name__ == "__main__":
    unittest.main()
