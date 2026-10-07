"""Les données simulées sont-elles cohérentes ?"""

import unittest

from netdiag.generate import SPECS, build
from netdiag.scenarios import list_scenario_ids, load_ground_truth, load_network, load_scenario
from netdiag.topology import domain_of


class TestScenarios(unittest.TestCase):
    def test_fifteen_scenarios_split_in_two_disjoint_sets(self):
        dev, test = list_scenario_ids("dev"), list_scenario_ids("test")
        self.assertEqual(len(list_scenario_ids()), 15)
        self.assertEqual((len(dev), len(test)), (5, 10))
        self.assertEqual(set(dev) & set(test), set())
        self.assertEqual(sorted(dev + test), list_scenario_ids())

    def test_every_expected_root_cause_exists_in_the_network(self):
        network = load_network()
        for scenario_id, truth in load_ground_truth().items():
            with self.subTest(scenario_id):
                self.assertEqual(truth["domain"], domain_of(truth["element"]))
                self.assertIn(truth["fault"], network["fault_types"])

    def test_a_scenario_never_contains_its_answer(self):
        # Ce qu'un agent peut lire : le ticket et les quatre sortes de traces. Rien d'autre.
        for scenario_id in list_scenario_ids():
            with self.subTest(scenario_id):
                self.assertEqual(
                    set(load_scenario(scenario_id)),
                    {"id", "ticket", "alarms", "kpis", "config_changes", "logs"},
                )

    def test_every_scenario_shows_the_same_dashboard(self):
        # Les 27 mesures sont toujours toutes présentes : la liste des mesures affichées
        # ne trahit donc pas l'endroit de la panne.
        dashboards = {
            scenario_id: [(k["element"], k["name"]) for k in load_scenario(scenario_id)["kpis"]]
            for scenario_id in list_scenario_ids()
        }
        reference = dashboards["SC01"]
        self.assertEqual(len(reference), 27)
        for scenario_id, dashboard in dashboards.items():
            with self.subTest(scenario_id):
                self.assertEqual(dashboard, reference)

    def test_generation_is_reproducible(self):
        # Relancer le générateur redonne exactement les fichiers enregistrés.
        for spec in SPECS:
            with self.subTest(spec["id"]):
                self.assertEqual(build(spec), load_scenario(spec["id"]))


if __name__ == "__main__":
    unittest.main()
