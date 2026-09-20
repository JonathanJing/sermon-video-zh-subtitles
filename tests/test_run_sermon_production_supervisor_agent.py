import argparse
import asyncio
import hashlib
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import run_sermon_production_supervisor_agent as mod
from scripts import sermon_production_supervisor


class RunSermonProductionSupervisorAgentTest(unittest.TestCase):
    def test_shadow_agent_exposes_only_read_tool(self):
        agent = mod.build_agent(model="gpt-6-astra", execute=False)
        self.assertEqual(agent.name, "Sermon Production Supervisor")
        self.assertEqual([tool.name for tool in agent.tools], ["inspect_production_state"])
        self.assertIs(agent.output_type, mod.SupervisorDecision)

    def test_execute_agent_exposes_bounded_mutation_tools(self):
        agent = mod.build_agent(model="gpt-6-astra", execute=True)
        self.assertEqual(
            [tool.name for tool in agent.tools],
            [
                "inspect_production_state",
                "run_timeline_probe",
                "run_approved_reading_pdf_generation",
            ],
        )
        self.assertIn("Never accept a start or end time", mod.SUPERVISOR_INSTRUCTIONS)
        self.assertIn("more than once", mod.SUPERVISOR_INSTRUCTIONS)
        self.assertIn("never transcribes or proposes boundaries", mod.SUPERVISOR_INSTRUCTIONS)

    def test_runtime_allows_each_mutation_stage_only_once(self):
        runtime = mod.SupervisorRuntime(
            config=sermon_production_supervisor.SupervisorConfig(
                sunday="2026-08-02",
                state_file="state.json",
                work_root=Path("artifacts"),
                gcs_bucket=None,
            ),
            execute=True,
        )

        self.assertTrue(mod.claim_stage_attempt(runtime, "timeline"))
        self.assertFalse(mod.claim_stage_attempt(runtime, "timeline"))
        self.assertTrue(mod.claim_stage_attempt(runtime, "generation"))
        self.assertFalse(mod.claim_stage_attempt(runtime, "generation"))

    def test_prompt_uses_each_backends_actual_state_and_output_contract(self):
        remote = mod.supervisor_instructions("agents-api")
        sdk = mod.supervisor_instructions("sdk")
        self.assertIn("windowApprovalValid", remote)
        self.assertIn("reasonCode", remote)
        self.assertIn("submit_supervisor_decision", remote)
        self.assertNotIn("windowApproval.valid", remote)
        self.assertIn("windowApproval.valid", sdk)
        self.assertNotIn("windowApprovalValid", sdk)
        self.assertNotIn("submit_supervisor_decision", sdk)

    def test_default_prompts_preserve_existing_session_payload_fingerprints(self):
        # Captured from b167094, before the optional page-release extension.
        # Even whitespace changes invalidate the Agents API resume payload.
        legacy_hashes = {
            "agents-api": "dc9169948b3a37f0f07f9a9701ccaa015024b791e35c2a1ae3aa2a1898275914",
            "sdk": "e039230aa898dc86a7553e3a2299a9cc9258e44495921d64895fe3d88b983474",
        }
        for backend, expected in legacy_hashes.items():
            with self.subTest(backend=backend):
                instructions = mod.supervisor_instructions(backend)
                self.assertEqual(hashlib.sha256(instructions.encode()).hexdigest(), expected)
                self.assertNotIn("wait_for_workflow_job", instructions)

    def test_runner_selects_extended_prompt_only_for_explicit_release_config(self):
        args = argparse.Namespace(approve_window=False, mode="shadow", agent_backend="agents-api")
        for release_config in (None, Path("release.json")):
            with self.subTest(release_config=release_config):
                config = sermon_production_supervisor.SupervisorConfig(
                    sunday="2026-08-02", state_file="state.json", work_root=Path("artifacts"),
                    gcs_bucket=None, api_key_secret=None, release_workflow_config=release_config,
                )
                with patch.object(mod, "make_config", return_value=config), patch(
                    "scripts.sermon_agents_supervisor.session_report", return_value={}
                ) as report:
                    asyncio.run(mod.run_agent(args))
                instructions = report.call_args.args[2]
                self.assertEqual(
                    instructions,
                    mod.supervisor_instructions("agents-api", page_release=release_config is not None),
                )
                self.assertEqual("wait_for_workflow_job" in instructions, release_config is not None)

    def test_verifier_does_not_accept_actionable_execute_as_observation(self):
        for next_action in ("run_timeline_probe", "resume_failed_timeline", "run_reading_pdf_generation"):
            with self.subTest(action=next_action):
                model = {"status": "observed", "action": next_action, "human_action_required": False,
                         "summary_zh": "等待下次", "evidence": []}
                state = {"recommendedAction": {"action": next_action, "humanActionRequired": False}}
                execute = mod.verify_decision(model, state, "execute")
                self.assertEqual(execute["status"], "blocked")
                self.assertFalse(execute["modelDecisionAccepted"])
                self.assertFalse(execute["human_action_required"])
                self.assertEqual(mod.verify_decision(model, state, "shadow")["status"], "observed")

    def test_false_model_complete_is_clamped_by_durable_state(self):
        decision = mod.verify_decision(
            {
                "status": "complete",
                "action": "complete",
                "summary_zh": "完成",
                "human_action_required": False,
                "evidence": [],
            },
            {
                "recommendedAction": {
                    "action": "request_window_approval",
                    "reason": "Human approval is missing.",
                    "humanActionRequired": True,
                }
            },
            "execute",
        )

        self.assertEqual(decision["status"], "blocked")
        self.assertEqual(decision["action"], "request_window_approval")
        self.assertFalse(decision["modelDecisionAccepted"])

    def test_durable_complete_overrides_model_wording(self):
        decision = mod.verify_decision(
            {
                "status": "blocked",
                "action": "inspect_quality_evidence",
                "summary_zh": "仍需审核",
                "human_action_required": True,
                "evidence": [],
            },
            {
                "recommendedAction": {
                    "action": "complete",
                    "reason": "All required reports passed.",
                    "humanActionRequired": False,
                }
            },
            "execute",
        )

        self.assertEqual(decision["status"], "complete")
        self.assertEqual(decision["action"], "complete")


if __name__ == "__main__":
    unittest.main()
