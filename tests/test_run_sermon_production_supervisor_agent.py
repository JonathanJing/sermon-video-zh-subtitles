import unittest
from pathlib import Path

from scripts import run_sermon_production_supervisor_agent as mod
from scripts import sermon_production_supervisor


class RunSermonProductionSupervisorAgentTest(unittest.TestCase):
    def test_shadow_agent_exposes_only_read_tool(self):
        agent = mod.build_agent(model="gpt-5.6", execute=False)
        self.assertEqual(agent.name, "Sermon Production Supervisor")
        self.assertEqual([tool.name for tool in agent.tools], ["inspect_production_state"])
        self.assertIs(agent.output_type, mod.SupervisorDecision)

    def test_execute_agent_exposes_bounded_mutation_tools(self):
        agent = mod.build_agent(model="gpt-5.6", execute=True)
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
