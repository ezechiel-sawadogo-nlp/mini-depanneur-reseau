"""La mécanique des agents, vérifiée avec un faux modèle (voir fake_model.py)."""

import unittest

from netdiag.agent import ALL_SOURCES, KINDS, MAX_REMINDERS, MAX_TURNS, REMINDER, diagnose, run_agent
from netdiag.agent import diagnosis_ask, diagnosis_schema, system_prompt
from netdiag.scenarios import load_scenario
from netdiag.team import diagnose_team, parse_report
from tests.fake_model import Recorder, json_reply, reply

L1_CUT = {"domain": "transport", "element": "L1", "fault": "fiber_cut"}


def is_final(request: dict) -> bool:
    """Le dernier appel d'un agent est le seul à imposer un format de réponse."""
    return "format" in request


class TestSingleAgent(unittest.TestCase):
    def setUp(self):
        self.scenario = load_scenario("SC01")

    def test_the_loop_runs_tools_then_returns_a_structured_diagnosis(self):
        script = iter([
            reply([("get_alarms", {"domain": "transport"})], "Je regarde le transport."),
            reply(content="La fibre L1 est coupée."),
        ])
        chat = Recorder(lambda **kw: json_reply(L1_CUT) if is_final(kw) else next(script))
        run = diagnose(self.scenario, chat=chat)

        self.assertEqual(run["diagnosis"], L1_CUT)
        self.assertEqual(run["consulted"], ["alarms:transport"])
        self.assertEqual(run["model_calls"], 3)  # deux tours d'enquête + la conclusion
        # Le résultat de l'outil a bien été remis au modèle au tour suivant.
        tool_message = chat.requests[1]["messages"][-1]
        self.assertEqual(tool_message["role"], "tool")
        self.assertIn("L1 LINK_DOWN", tool_message["content"])

    def test_a_tool_error_goes_back_to_the_model_and_the_run_continues(self):
        script = iter([
            reply([("get_logs", {"domain": "ran", "element": "C2"})]),  # argument inventé
            reply([("get_logs", {"domain": "ran"})]),                   # le modèle se corrige
            reply(content="Conclusion."),
        ])
        chat = Recorder(lambda **kw: json_reply(L1_CUT) if is_final(kw) else next(script))
        run = diagnose(self.scenario, chat=chat)

        self.assertTrue(chat.requests[1]["messages"][-1]["content"].startswith("ERREUR"))
        self.assertEqual((run["tool_calls"], run["tool_errors"]), (2, 1))
        self.assertEqual(run["diagnosis"], L1_CUT)

    def test_the_turn_cap_stops_a_model_that_never_concludes(self):
        chat = Recorder(
            lambda **kw: json_reply(L1_CUT) if is_final(kw) else reply([("get_alarms", {"domain": "ran"})])
        )
        run = diagnose(self.scenario, chat=chat)

        self.assertEqual(run["turns"], MAX_TURNS)
        self.assertTrue(run["hit_turn_limit"])
        self.assertEqual(run["diagnosis"], L1_CUT)  # il rend quand même une réponse

    def test_an_unusable_answer_gives_no_diagnosis(self):
        for text in ["pas du JSON", '{"domain": "transport"}', '{"domain": "x", "element": "L1", "fault": "fiber_cut"}']:
            with self.subTest(text):
                chat = lambda **kw: reply(content=text) if is_final(kw) else reply(content="fin")
                self.assertIsNone(diagnose(self.scenario, chat=chat)["diagnosis"])

    def run_with_coverage(self, chat):
        return run_agent(
            self.scenario, system=system_prompt(), user="Ticket : test",
            final_schema=diagnosis_schema(), final_ask=diagnosis_ask(),
            required=ALL_SOURCES, chat=chat,
        )

    def test_the_coverage_guard_asks_for_the_missing_sources(self):
        everything = [(f"get_{kind}", {"domain": domain}) for domain in ("ran", "transport", "core") for kind in KINDS]
        script = iter([
            reply([("get_alarms", {"domain": "ran"})]),
            reply(content="Je conclus."),  # trop tôt : onze sources manquent
            reply(everything),
            reply(content="Conclusion."),
        ])
        chat = Recorder(lambda **kw: json_reply(L1_CUT) if is_final(kw) else next(script))
        final = self.run_with_coverage(chat)

        reminders = [m for m in final["messages"] if m["role"] == "user" and m["content"].startswith(REMINDER)]
        self.assertEqual(len(reminders), 1)
        self.assertIn("get_kpis(domain='ran')", reminders[0]["content"])
        self.assertNotIn("get_alarms(domain='ran')", reminders[0]["content"])  # déjà consultée

    def test_the_coverage_guard_gives_up_on_a_stubborn_model(self):
        # Observé avec le vrai modèle : il peut ignorer les rappels. Le garde-fou insiste
        # un nombre limité de fois, puis laisse conclure au lieu de tourner en rond.
        chat = Recorder(lambda **kw: json_reply(L1_CUT) if is_final(kw) else reply(content="Non."))
        final = self.run_with_coverage(chat)

        reminders = [m for m in final["messages"] if m["role"] == "user" and m["content"].startswith(REMINDER)]
        self.assertEqual(len(reminders), MAX_REMINDERS)
        self.assertEqual(final["answer"], json_reply(L1_CUT).message.content)


class TestTeam(unittest.TestCase):
    def fake_team(self, reports: dict):
        """Un faux modèle qui joue les quatre rôles, reconnus à leurs consignes."""

        def answer(**kw):
            system = kw["messages"][0]["content"]
            if "Tu es l'orchestrateur" in system:
                return json_reply({"analysis": "Le transport se déclare cause.", **L1_CUT})
            domain = next(d for d in ("ran", "transport", "core") if f"spécialiste du domaine {d}" in system)
            if is_final(kw):
                return json_reply(reports[domain])
            return reply([(f"get_{kind}", {"domain": domain}) for kind in KINDS])

        return Recorder(answer)

    reports = {
        "ran": {"analysis": "a", "affected_elements": ["C1", "C2", "S1"], "status": "impacted",
                "element": "none", "fault": "none", "first_event_time": "10:01:05"},
        "transport": {"analysis": "b", "affected_elements": ["L1"], "status": "local_cause",
                      "element": "L1", "fault": "fiber_cut", "first_event_time": "10:01:02"},
        "core": {"analysis": "c", "affected_elements": [], "status": "impacted",
                 "element": "none", "fault": "none", "first_event_time": "10:01:09"},
    }

    def test_each_domain_agent_sees_only_its_domain(self):
        chat = self.fake_team(self.reports)
        run = diagnose_team(load_scenario("SC01"), chat=chat)

        for request in chat.requests:
            system = request["messages"][0]["content"]
            if "Tu es l'orchestrateur" in system:
                self.assertNotIn("tools", request)  # l'orchestrateur n'a aucun outil
                continue
            domain = next(d for d in ("ran", "transport", "core") if f"spécialiste du domaine {d}" in system)
            for schema in request["tools"]:
                self.assertEqual(schema["function"]["parameters"]["properties"]["domain"]["enum"], [domain])
            for message in request["messages"]:
                if message["role"] == "tool" and domain != "transport":
                    self.assertNotIn("LINK_DOWN", message["content"])  # alarme du transport
        self.assertEqual(len(set(run["consulted"])), 12)
        self.assertEqual(run["model_calls"], 7)  # 3 agents x 2 appels + l'orchestrateur

    def test_the_orchestrator_gets_reports_and_scope_analysis_but_no_raw_data(self):
        chat = self.fake_team(self.reports)
        run = diagnose_team(load_scenario("SC01"), chat=chat)

        asked = chat.requests[-1]["messages"][-1]["content"]
        for domain in ("ran", "transport", "core"):
            self.assertIn(f"Rapport de l'agent {domain}", asked)
        self.assertIn("éléments suspects, de l'aval vers l'amont : S1, L1", asked)
        self.assertIn("éléments innocentés : R1, L3, AMF, SMF, UPF", asked)
        self.assertNotIn("optical rx power", asked)  # un log brut du scénario
        self.assertEqual(run["diagnosis"], L1_CUT)

    def test_an_unreadable_report_is_flagged_not_hidden(self):
        self.assertEqual(parse_report("pas du JSON", "ran")["status"], "unreadable")
        self.assertEqual(parse_report('{"status": "healthy"}', "core")["status"], "unreadable")


if __name__ == "__main__":
    unittest.main()
