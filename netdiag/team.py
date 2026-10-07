"""Étape 5 : un orchestrateur et trois agents de domaine.

    START -> agent ran -> agent transport -> agent core -> orchestrateur -> END

Chaque agent de domaine ne voit que les données de son domaine et rend un rapport.
L'orchestrateur ne voit aucune donnée du réseau : seulement le ticket, les rapports,
et une analyse de périmètre que le code calcule à partir de la topologie.

Usage :
    python -m netdiag.team SC05
"""

import json
import operator
import sys
from typing import Annotated, TypedDict

import ollama
from langgraph.graph import END, START, StateGraph

from netdiag.agent import (
    KINDS, MODEL, OPTIONS, diagnosis_schema, measure, network_description,
    parse_diagnosis, print_usage, run_agent, summarize,
)
from netdiag.scenarios import load_network, load_scenario
from netdiag.scope import build_graph as build_scope_graph
from netdiag.tools import DOMAINS
from netdiag.topology import all_cells, all_sites, cells_behind

DOMAIN_MAX_TURNS = 4  # un agent de domaine n'a que quatre sources à consulter
# Le statut local_cause exige une preuve : sans cette exigence, chaque agent a tendance
# à se déclarer coupable (observé sur SC05 : les trois agents se disaient cause locale).
STATUSES = {
    "healthy": "aucune mesure de ton domaine n'a changé de façon notable pendant l'incident."
    " Un simple avertissement mineur, sans mesure anormale, ne compte pas",
    "impacted": "des mesures de ton domaine ont changé, mais aucune alarme ni aucun log ne"
    " décrit une défaillance née dans ton domaine au début des symptômes",
    "local_cause": "tu as une preuve directe : une alarme ou un log qui décrit la défaillance"
    " d'un élément de ton domaine au début des symptômes, ou un changement de configuration"
    " appliqué sur l'élément touché dans l'heure qui précède. Donne l'élément et le type de panne",
}


class TeamState(TypedDict):
    ticket: str
    # Trois agents écrivent dans la même clé : le reducer empile leurs rapports
    # au lieu de laisser le dernier écraser les précédents.
    reports: Annotated[list[dict], operator.add]
    runs: Annotated[list[dict], operator.add]  # ce que chaque agent a fait et coûté
    analysis: str  # le raisonnement de l'orchestrateur
    diagnosis: dict | None


# --- Les agents de domaine ---------------------------------------------------------

def domain_prompt(domain: str) -> str:
    """Les consignes d'un agent de domaine. La description du réseau vient en premier :
    elle est commune aux quatre prompts de l'équipe, donc elle reste dans le cache."""
    elements = ", ".join(load_network()["domains"][domain])
    statuses = "\n".join(f"   - {name} : {text}" for name, text in STATUSES.items())
    return "\n".join([
        network_description(),
        "",
        f"Tu es l'agent spécialiste du domaine {domain}. Tu ne vois que les données de ce"
        f" domaine ({elements}).",
        "On te donne un ticket d'incident. Un orchestrateur interroge aussi les agents des"
        " autres domaines, puis décidera de la cause racine à partir des rapports.",
        "",
        "Ta mission :",
        "1. Appelle les quatre outils (alarmes, mesures, logs, changements de configuration)"
        " en une seule fois, sans rien écrire avant.",
        "2. Compare avant et pendant l'incident : quels éléments de ton domaine ont des mesures"
        " anormales, et à quelle heure commence le premier événement lié au ticket ?",
        "3. Rends ton rapport avec l'un de ces statuts :",
        statuses,
        "",
        "Repères :",
        "- Tu ne vois qu'un domaine : un symptôme chez toi peut venir d'un élément dont tes"
        " équipements dépendent. Dans ce cas ton statut est impacted, pas local_cause.",
        "- Un événement daté de plusieurs heures avant les symptômes n'est pas une preuve.",
    ])


def report_schema(domain: str) -> dict:
    """Le format du rapport d'un agent de domaine. Le champ analysis vient en premier :
    le modèle rédige son raisonnement avant de choisir un statut."""
    net = load_network()
    return {
        "type": "object",
        "properties": {
            "analysis": {"type": "string"},
            "affected_elements": {
                "type": "array", "items": {"type": "string", "enum": list(net["domains"][domain])},
            },
            "status": {"type": "string", "enum": list(STATUSES)},
            "element": {"type": "string", "enum": list(net["domains"][domain]) + ["none"]},
            "fault": {"type": "string", "enum": list(net["fault_types"]) + ["none"]},
            "first_event_time": {"type": "string"},
        },
        "required": ["analysis", "affected_elements", "status", "element", "fault", "first_event_time"],
    }


def report_ask(domain: str) -> str:
    schema = report_schema(domain)["properties"]
    choices = {key: schema[key]["enum"] for key in ("status", "element", "fault")}
    return (
        "Rédige maintenant ton rapport en JSON avec exactement ces champs : analysis (ce que"
        " tu observes et ce que tu en conclus, en quelques phrases), affected_elements (la liste"
        " des éléments de ton domaine dont les mesures sont anormales pendant l'incident, vide"
        " s'il n'y en a pas), status, element, fault, first_event_time (HH:MM:SS, ou vide si"
        f" rien d'anormal). Valeurs possibles : {json.dumps(choices, ensure_ascii=False)}"
    )


def parse_report(text: str | None, domain: str) -> dict:
    """Transforme la réponse d'un agent en rapport. Un rapport illisible est signalé
    comme tel à l'orchestrateur, jamais remplacé par un rapport rassurant."""
    schema = report_schema(domain)["properties"]
    try:
        data = json.loads(text)
        report = {key: data[key] for key in schema}
        valid = all(report[key] in schema[key]["enum"] for key in ("status", "element", "fault"))
        valid = valid and all(e in schema["element"]["enum"] for e in report["affected_elements"])
    except (json.JSONDecodeError, KeyError, TypeError):
        valid = False
    if not valid:
        return {"domain": domain, "status": "unreadable", "element": "none", "fault": "none",
                "affected_elements": [], "first_event_time": "", "analysis": "rapport illisible"}
    return {"domain": domain, **report}


# --- L'orchestrateur -----------------------------------------------------------------

def orchestrator_prompt() -> str:
    return "\n".join([
        network_description(),
        "",
        "Tu es l'orchestrateur d'une équipe de diagnostic. Tu ne vois aucune donnée du réseau :"
        " seulement le ticket et les rapports de trois agents (ran, transport, core)."
        " Chaque agent ne voit que son domaine.",
        "Trouve la cause racine : l'événement initial qui explique tous les symptômes.",
        "",
        "Méthode :",
        "1. Un élément innocenté par l'analyse de périmètre ne peut pas être la cause, même si"
        " un agent l'accuse : des cellules saines en dépendent, donc il fonctionne.",
        "2. Parmi les éléments suspects, retiens ceux qu'un agent désigne avec le statut"
        " local_cause.",
        "3. S'il en reste plusieurs, la cause est le plus en amont, c'est-à-dire le dernier de"
        " la liste des suspects : sa panne explique les symptômes des éléments qui dépendent de"
        " lui, alors que l'inverse est impossible.",
        "4. S'il n'en reste aucun, choisis parmi les suspects celui que les rapports décrivent"
        " comme le plus directement défaillant.",
    ])


def orchestrator_schema() -> dict:
    """Le diagnostic, précédé d'un champ analysis où le modèle raisonne d'abord."""
    schema = diagnosis_schema()
    return {
        "type": "object",
        "properties": {"analysis": {"type": "string"}, **schema["properties"]},
        "required": ["analysis"] + schema["required"],
    }


def format_report(report: dict) -> str:
    return (
        f"Rapport de l'agent {report['domain']} : statut {report['status']} ; élément"
        f" {report['element']} ; panne {report['fault']} ; éléments anormaux"
        f" {', '.join(report['affected_elements']) or 'aucun'} ; premier événement"
        f" {report['first_event_time'] or 'aucun'} ; analyse : {report['analysis']}"
    )


def scope_facts(reports: list[dict]) -> str:
    """L'analyse de périmètre, calculée par le code et non par le modèle.

    On part des cellules que l'agent ran déclare touchées, et on réutilise le graphe
    de l'étape 2a : garder ce que les cellules touchées ont en commun, puis innocenter
    tout ce qu'une cellule saine utilise aussi.
    """
    listed = next((r["affected_elements"] for r in reports if r["domain"] == "ran"), [])
    affected = sorted(
        {e for e in listed if e in all_cells()}
        | {cell for site in listed if site in all_sites() for cell in cells_behind(site)}
    )
    if not affected:
        return "Analyse de périmètre : impossible, l'agent ran ne signale aucune cellule touchée."
    healthy = [cell for cell in all_cells() if cell not in affected]
    scope = build_scope_graph().invoke({"affected": affected, "healthy": healthy})
    return "\n".join([
        "Analyse de périmètre (calculée à partir de la topologie, donc fiable) :",
        f"- cellules touchées : {', '.join(affected)} ; cellules saines : {', '.join(healthy) or 'aucune'}",
        f"- éléments suspects, de l'aval vers l'amont : {', '.join(scope['suspects'])}",
        f"- éléments innocentés : {', '.join(scope['cleared']) or 'aucun'}",
    ])


def orchestrator_ask(ticket: str, reports: list[dict]) -> str:
    properties = diagnosis_schema()["properties"]
    choices = json.dumps({key: value["enum"] for key, value in properties.items()}, ensure_ascii=False)
    return "\n".join(
        [f"Ticket : {ticket}", ""]
        + [format_report(r) for r in reports]
        + ["", scope_facts(reports)]
        + ["", "Réponds en JSON avec exactement ces champs : analysis (ton raisonnement en"
           f" quelques phrases), domain, element, fault. Valeurs possibles : {choices}"]
    )


# --- Le graphe de l'équipe ---------------------------------------------------------------

def build_team(scenario: dict, chat=ollama.chat, trace: bool = False):
    """Construit le graphe : trois agents de domaine en séquence, puis l'orchestrateur."""

    def make_domain_node(domain: str):
        def node(state: TeamState) -> dict:
            if trace:
                print(f"\n--- Agent {domain} ---")
            final = run_agent(
                scenario,
                system=domain_prompt(domain),
                user=f"Ticket : {state['ticket']}",
                final_schema=report_schema(domain),
                final_ask=report_ask(domain),
                allowed_domains=[domain],  # cloisonnement : il ne peut rien lire d'autre
                required=[f"{kind}:{domain}" for kind in KINDS],  # couverture imposée
                direct_report=True,  # le raisonnement s'écrit dans le rapport
                max_turns=DOMAIN_MAX_TURNS,
                chat=chat,
                trace=trace,
            )
            report = parse_report(final["answer"], domain)
            if trace:
                print(format_report(report))
            return {"reports": [report], "runs": [{"agent": domain, **summarize(final)}]}

        return node

    def orchestrator(state: TeamState) -> dict:
        """Un seul appel au modèle : corréler les trois rapports et trancher."""
        messages = [
            {"role": "system", "content": orchestrator_prompt()},
            {"role": "user", "content": orchestrator_ask(state["ticket"], state["reports"])},
        ]
        response = chat(model=MODEL, messages=messages, format=orchestrator_schema(), options=OPTIONS)
        text = response.message.content
        try:
            analysis = str(json.loads(text).get("analysis", ""))
        except (json.JSONDecodeError, AttributeError, TypeError):
            analysis = ""
        usage = measure("orchestrator", response)
        if trace:
            print("\n--- Orchestrateur ---")
            print(scope_facts(state["reports"]))
            print_usage(usage)
            print(f"analyse : {analysis}")
        run = {
            "agent": "orchestrator", "consulted": [], "reasoning": [analysis], "turns": 1,
            "tool_calls": 0, "tool_errors": 0, "hit_turn_limit": False, "model_calls": 1,
            **{key: usage[key] for key in ("prompt_tokens", "output_tokens", "prompt_seconds", "output_seconds")},
        }
        return {"analysis": analysis, "diagnosis": parse_diagnosis(text), "runs": [run]}

    builder = StateGraph(TeamState)
    previous = START
    for domain in DOMAINS:
        builder.add_node(f"agent_{domain}", make_domain_node(domain))
        builder.add_edge(previous, f"agent_{domain}")
        previous = f"agent_{domain}"
    builder.add_node("orchestrator", orchestrator)
    builder.add_edge(previous, "orchestrator")
    builder.add_edge("orchestrator", END)
    return builder.compile()


def diagnose_team(scenario: dict, chat=ollama.chat, trace: bool = False) -> dict:
    """Lance l'équipe sur un scénario et résume ce qui s'est passé, agent par agent."""
    initial = {"ticket": scenario["ticket"], "reports": [], "runs": [], "analysis": "", "diagnosis": None}
    final = build_team(scenario, chat=chat, trace=trace).invoke(initial)
    runs = final["runs"]
    totals = {
        key: round(sum(r[key] for r in runs), 1)
        for key in ("turns", "tool_calls", "tool_errors", "model_calls", "prompt_tokens",
                    "output_tokens", "prompt_seconds", "output_seconds")
    }
    return {
        "diagnosis": final["diagnosis"],
        "reports": final["reports"],
        "consulted": [source for r in runs for source in r["consulted"]],
        "reasoning": [format_report(r) for r in final["reports"]] + [f"Orchestrateur : {final['analysis']}"],
        "hit_turn_limit": any(r["hit_turn_limit"] for r in runs),
        **totals,
    }


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    scenario = load_scenario(sys.argv[1])
    print(f"=== {scenario['id']} ===\nTicket : {scenario['ticket']}")
    run = diagnose_team(scenario, trace=True)
    print(f"\nDiagnostic structuré : {run['diagnosis']}")
    print(
        f"Coût : {run['model_calls']} appels au modèle, {run['tool_calls']} appels d'outils,"
        f" {run['prompt_tokens']} tokens lus, {run['output_tokens']} tokens écrits"
    )


if __name__ == "__main__":
    main()
