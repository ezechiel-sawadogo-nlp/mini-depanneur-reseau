"""Les outils et l'analyse de périmètre : du code sans modèle, donc vérifiable à 100 %."""

import unittest

from netdiag.evaluate import score
from netdiag.scenarios import load_scenario
from netdiag.scope import build_graph, scope_facts
from netdiag.tools import make_tools, run_tool


class TestTools(unittest.TestCase):
    def setUp(self):
        self.scenario = load_scenario("SC01")  # fibre L1 coupée

    def test_a_tool_returns_only_the_rows_of_the_requested_domain(self):
        _, functions = make_tools(self.scenario)
        alarms = run_tool(functions, "get_alarms", {"domain": "transport"})
        self.assertIn("L1 LINK_DOWN", alarms)
        self.assertNotIn("CELL_OUT_OF_SERVICE", alarms)  # alarme du domaine ran

    def test_a_domain_agent_cannot_read_another_domain(self):
        schemas, functions = make_tools(self.scenario, allowed_domains=["ran"])
        # Le schéma ne propose que son domaine...
        for schema in schemas:
            self.assertEqual(schema["function"]["parameters"]["properties"]["domain"]["enum"], ["ran"])
        # ...et même si le modèle demande autre chose, le code refuse.
        answer = run_tool(functions, "get_alarms", {"domain": "transport"})
        self.assertTrue(answer.startswith("ERREUR"))
        self.assertNotIn("LINK_DOWN", answer)

    def test_a_tool_error_is_a_text_not_a_crash(self):
        _, functions = make_tools(self.scenario)
        for name, arguments in [
            ("get_weather", {"domain": "ran"}),              # outil inconnu
            ("get_logs", {"domain": "ran", "element": "C2"}),  # argument en trop
            ("get_logs", {}),                                 # argument manquant
            ("get_logs", {"domain": "internet"}),            # domaine inconnu
        ]:
            with self.subTest(name=name, arguments=arguments):
                self.assertTrue(run_tool(functions, name, arguments).startswith("ERREUR"))

    def test_nothing_to_report_is_not_an_error(self):
        _, functions = make_tools(self.scenario)
        answer = run_tool(functions, "get_config_changes", {"domain": "core"})
        self.assertFalse(answer.startswith("ERREUR"))
        self.assertIn("Aucun changement", answer)


class TestScope(unittest.TestCase):
    def analyse(self, affected, healthy):
        return build_graph().invoke({"affected": affected, "healthy": healthy})

    def test_one_site_down(self):
        result = self.analyse(["C1", "C2"], ["C3"])
        self.assertEqual(result["suspects"], ["S1", "L1"])
        self.assertEqual(result["cleared"], ["R1", "L3", "AMF", "SMF", "UPF"])

    def test_one_cell_down(self):
        self.assertEqual(self.analyse(["C1"], ["C2", "C3"])["suspects"], ["C1"])

    def test_whole_network_down_clears_nobody(self):
        result = self.analyse(["C1", "C2", "C3"], [])
        self.assertEqual(result["suspects"], ["R1", "L3", "AMF", "SMF", "UPF"])
        self.assertEqual(result["cleared"], [])

    def test_a_site_stands_for_its_cells(self):
        self.assertEqual(scope_facts(["S1"]), scope_facts(["C1", "C2"]))

    def test_a_forgotten_cell_gives_a_wrong_analysis(self):
        # Limite connue, observée sur le scénario SC13 : le calcul est juste, mais il part
        # de la liste écrite par le modèle. Si celui-ci oublie C2 alors que tout le réseau
        # est touché, C2 passe pour saine et innocente à tort tous les éléments.
        result = self.analyse(["C1", "C3"], ["C2"])
        self.assertEqual(result["suspects"], [])
        self.assertEqual(result["cleared"], ["R1", "L3", "AMF", "SMF", "UPF"])

    def test_no_affected_cell(self):
        self.assertIn("impossible", scope_facts([]))


class TestScore(unittest.TestCase):
    expected = {"domain": "transport", "element": "L1", "fault": "fiber_cut"}

    def test_exact(self):
        self.assertTrue(score(dict(self.expected), self.expected)["exact"])

    def test_right_place_wrong_fault(self):
        result = score({**self.expected, "fault": "link_congestion"}, self.expected)
        self.assertEqual(
            result, {"domain": True, "element": True, "fault": False, "exact": False}
        )

    def test_no_diagnosis_counts_as_an_error(self):
        self.assertEqual(set(score(None, self.expected).values()), {False})


if __name__ == "__main__":
    unittest.main()
