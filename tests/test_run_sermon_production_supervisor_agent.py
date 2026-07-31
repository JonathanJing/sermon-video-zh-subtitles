import unittest

from scripts import run_sermon_production_supervisor_agent as mod


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


if __name__ == "__main__":
    unittest.main()
