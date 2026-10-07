"""Un agent : il enquête par appels d'outils, puis rend une réponse structurée.

    START -> call_model -> (outils demandés ?)     -> run_tools -> call_model -> ...
                        -> (sources manquantes ?)  -> remind    -> call_model -> ...
                        -> (sinon)                 -> conclude  -> END

Le même graphe sert à l'agent seul (ce fichier) et aux agents de domaine (team.py) :
seuls changent les consignes, les domaines autorisés et le format de la réponse.

Usage :
    python -m netdiag.agent SC01
    python -m netdiag.agent SC01 --aided          # agent seul avec les mêmes aides que l'équipe
    python -m netdiag.agent SC01 --brief-prompt   # variante écartée (consigne de brièveté)
"""

import json
import operator
import sys
from typing import Annotated, TypedDict

import ollama
from langgraph.graph import END, START, StateGraph

from netdiag.scenarios import load_network, load_scenario
from netdiag.scope import scope_facts
from netdiag.tools import DOMAINS, make_tools, run_tool
from netdiag.topology import all_cells

MODEL = "qwen2.5:7b"
MAX_TURNS = 8  # nombre maximal d'appels au modèle pendant l'enquête
# temperature 0 : réponses reproductibles. num_ctx : taille de la fenêtre de contexte.
OPTIONS = {"temperature": 0, "num_ctx": 8192}
REMINDER = "Avant de conclure, consulte aussi"
MAX_REMINDERS = 2  # rappels de couverture avant de laisser l'agent conclure quand même
KINDS = ["alarms", "kpis", "logs", "config_changes"]  # les quatre sources d'un domaine
ALL_SOURCES = [f"{kind}:{domain}" for domain in DOMAINS for kind in KINDS]


class AgentState(TypedDict):
    # Annotated[..., operator.add] est un "reducer" : ce qu'un nœud renvoie pour
    # cette clé est AJOUTÉ à la liste existante au lieu de la remplacer.
    messages: Annotated[list[dict], operator.add]
    turns: int  # pas de reducer : la nouvelle valeur remplace l'ancienne
    answer: str | None  # la réponse finale brute (du JSON), écrite par le nœud conclude
    usage: Annotated[list[dict], operator.add]  # une mesure par appel au modèle


# --- Les textes donnés au modèle ---------------------------------------------------

def network_description() -> str:
    """Le réseau, ses dépendances et les types de panne, construits depuis network.json."""
    net = load_network()
    lines = ["Réseau :"]
    for domain, elements in net["domains"].items():
        described = ", ".join(f"{name} ({text})" for name, text in elements.items())
        lines.append(f"- {domain} : {described}")
    lines.append("")
    lines.append("Dépendances (un élément a besoin des suivants pour fonctionner) :")
    lines.append(" ; ".join(f"{e} -> {', '.join(deps)}" for e, deps in net["depends_on"].items()))
    lines.append("")
    lines.append("Types de panne possibles :")
    for fault, text in net["fault_types"].items():
        lines.append(f"- {fault} : {text}")
    return "\n".join(lines)


def system_prompt(brief: bool = False, aided: bool = False) -> str:
    """Les consignes de l'agent seul.

    aided : True ajoute les repères donnés aux agents de l'équipe (exigence de preuve),
    pour que la comparaison entre l'agent seul et l'équipe soit équitable.
    brief : True ajoute une consigne de brièveté. Mesuré sur 3 scénarios x 3 exécutions :
    2,3 fois plus rapide, mais 3 diagnostics justes sur 9 contre 9 sur 9 sans elle.
    La variante est conservée pour pouvoir refaire la comparaison ; elle n'est pas utilisée.
    """
    lines = [
        "Tu es un agent de diagnostic d'un réseau mobile. On te donne un ticket d'incident.",
        "Trouve la cause racine : l'événement initial qui explique tous les symptômes.",
        "",
        network_description(),
        "",
        "Méthode :",
        "1. Consulte les alarmes, mesures, logs et changements de configuration avec les outils."
        " Tu ne sais rien d'autre que ce que les outils renvoient.",
        "2. Périmètre : quels éléments sont touchés, lesquels fonctionnent encore ?"
        " Un élément utilisé par une cellule saine fonctionne.",
        "3. Chronologie : l'événement le plus ancien est le plus proche de la cause."
        " Les alarmes suivantes sont souvent des conséquences.",
        "4. Le type de panne se déduit des logs et des changements de configuration.",
        "",
    ]
    if aided:
        lines += [
            "Repères :",
            "- Un élément n'est la cause que si une alarme ou un log décrit sa défaillance au"
            " début des symptômes, ou si un changement de configuration lui a été appliqué dans"
            " l'heure qui précède.",
            "- Un événement daté de plusieurs heures avant les symptômes n'est pas une preuve."
            " Un simple avertissement mineur, sans mesure anormale, non plus.",
            "- Un symptôme sur un élément peut venir d'un élément dont il dépend.",
            "",
        ]
    if brief:
        lines += [
            "Sois bref. Quand tu appelles des outils, n'écris pas plus d'une phrase.",
            "Quand tu as assez d'éléments, n'appelle plus d'outil et conclus en trois lignes au"
            " plus : domaine, élément, type de panne (dans la liste ci-dessus), preuve principale.",
        ]
    else:
        lines += [
            "Quand tu as assez d'éléments, n'appelle plus d'outil et donne ta conclusion :"
            " domaine, élément, type de panne (dans la liste ci-dessus) et la preuve principale.",
        ]
    return "\n".join(lines)


def diagnosis_schema() -> dict:
    """Le format imposé au diagnostic : trois champs, chacun dans une liste fermée."""
    net = load_network()
    elements = [name for domain in net["domains"].values() for name in domain]
    return {
        "type": "object",
        "properties": {
            "domain": {"type": "string", "enum": list(net["domains"])},
            "element": {"type": "string", "enum": elements},
            "fault": {"type": "string", "enum": list(net["fault_types"])},
        },
        "required": ["domain", "element", "fault"],
    }


def diagnosis_ask() -> str:
    properties = json.dumps(diagnosis_schema()["properties"], ensure_ascii=False)
    return (
        "Donne maintenant ta conclusion finale en JSON, avec exactement ces champs"
        f" et ces valeurs possibles : {properties}"
    )


def parse_diagnosis(text: str | None) -> dict | None:
    """Transforme la réponse du modèle en diagnostic, ou None si elle est inutilisable."""
    schema = diagnosis_schema()["properties"]
    try:
        data = json.loads(text)
        diagnosis = {key: data[key] for key in ("domain", "element", "fault")}
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    if any(diagnosis[key] not in schema[key]["enum"] for key in diagnosis):
        return None
    return diagnosis


# --- Mesure et affichage -------------------------------------------------------------

def measure(node: str, response) -> dict:
    """Ce qu'un appel au modèle a coûté, d'après les compteurs renvoyés par Ollama.

    Les durées d'Ollama sont en nanosecondes. Un compteur absent vaut 0.
    """

    def read(name: str) -> int:
        return getattr(response, name, None) or 0

    return {
        "node": node,
        "prompt_tokens": read("prompt_eval_count"),  # tokens lus (l'historique)
        "output_tokens": read("eval_count"),  # tokens écrits (la réponse)
        "prompt_seconds": round(read("prompt_eval_duration") / 1e9, 1),
        "output_seconds": round(read("eval_duration") / 1e9, 1),
        "total_seconds": round(read("total_duration") / 1e9, 1),
    }


def print_message(message: dict) -> None:
    """Affiche un message de l'historique sous forme de trace lisible."""
    if message["role"] == "tool":
        print(f"  [outil] {message['tool_name']} a renvoyé :")
        for line in message["content"].splitlines():
            print(f"      {line}")
    elif message["role"] == "user":
        print(f"[rappel] {message['content']}")
    elif message.get("tool_calls"):
        if message.get("content"):
            print(f"[modèle] {message['content']}")
        for call in message["tool_calls"]:
            args = ", ".join(f"{k}={v!r}" for k, v in call["function"]["arguments"].items())
            print(f"[modèle] demande {call['function']['name']}({args})")
    else:
        print(f"[modèle] raisonnement :\n{message.get('content', '')}")


def print_usage(u: dict) -> None:
    print(
        f"  [mesure] {u['node']:<10} {u['prompt_tokens']:>5} tokens lus en"
        f" {u['prompt_seconds']:>5} s, {u['output_tokens']:>4} tokens écrits en"
        f" {u['output_seconds']:>5} s",
        flush=True,
    )


def consulted(messages: list[dict]) -> list[str]:
    """Les sources demandées par le modèle, dans l'ordre, sous la forme "alarms:ran"."""
    return [
        f"{call['function']['name'].removeprefix('get_')}:{call['function']['arguments'].get('domain', '?')}"
        for m in messages
        if m["role"] == "assistant"
        for call in m.get("tool_calls") or []
    ]


# --- Le graphe -------------------------------------------------------------------------

def build_agent(
    scenario: dict,
    final_schema: dict,
    final_ask: str,
    allowed_domains: list[str] = DOMAINS,
    required: list[str] = (),
    direct_report: bool = False,
    max_turns: int = MAX_TURNS,
    chat=ollama.chat,
    trace: bool = False,
):
    """Construit le graphe d'un agent pour un scénario.

    final_schema, final_ask : le format et la question de la réponse finale.
    allowed_domains : les domaines que cet agent a le droit de consulter.
    required : les sources que l'agent doit avoir consultées avant de conclure
               (par exemple "kpis:transport"). Vide = l'agent décide seul.
    direct_report : True pour passer à la réponse finale dès que les sources obligatoires
               sont consultées, sans tour de rédaction libre. Le raisonnement s'écrit alors
               dans la réponse structurée elle-même, ce qui économise un appel au modèle.
    chat : la fonction qui appelle le modèle. Par défaut Ollama ; dans les tests,
           on la remplace par une fausse fonction pour vérifier le graphe sans LLM.
    trace : True pour afficher chaque message au fil de l'eau.
    """
    schemas, functions = make_tools(scenario, allowed_domains)

    def show(messages: list[dict], usage: list[dict] = ()) -> None:
        if trace:
            for message in messages:
                print_message(message)
            for u in usage:
                print_usage(u)

    def missing(state: AgentState) -> list[str]:
        done = consulted(state["messages"])
        return [source for source in required if source not in done]

    def reminders(state: AgentState) -> int:
        return sum(m["role"] == "user" and m["content"].startswith(REMINDER) for m in state["messages"])

    def call_model(state: AgentState) -> dict:
        """Nœud 1 : le modèle lit tout l'historique et décide de la suite."""
        response = chat(model=MODEL, messages=state["messages"], tools=schemas, options=OPTIONS)
        message = response.message.model_dump(exclude_none=True)
        usage = [measure("call_model", response)]
        show([message], usage)
        return {"messages": [message], "turns": state["turns"] + 1, "usage": usage}

    def run_tools(state: AgentState) -> dict:
        """Nœud 2 : notre code exécute chaque outil demandé par le modèle."""
        results = []
        for call in state["messages"][-1]["tool_calls"]:
            name = call["function"]["name"]
            arguments = call["function"]["arguments"]
            content = run_tool(functions, name, arguments)
            results.append({"role": "tool", "tool_name": name, "content": content})
        show(results)
        return {"messages": results}

    def remind(state: AgentState) -> dict:
        """Nœud 3 : le garde-fou de couverture. Le code, pas le modèle, vérifie
        que les sources obligatoires ont été consultées, et les réclame sinon."""
        wanted = ", ".join(
            f"get_{source.split(':')[0]}(domain='{source.split(':')[1]}')" for source in missing(state)
        )
        message = {"role": "user", "content": f"{REMINDER} : {wanted}."}
        show([message])
        return {"messages": [message]}

    def conclude(state: AgentState) -> dict:
        """Nœud 4 : un dernier appel dont la réponse est contrainte au schéma."""
        history = state["messages"]
        if history[-1].get("tool_calls"):
            # plafond atteint : on retire la demande d'outils restée sans réponse
            history = history[:-1]
        ask = {"role": "user", "content": final_ask}
        # On repasse les mêmes outils : le début du prompt reste identique aux appels
        # précédents, donc Ollama réutilise son cache au lieu de tout relire.
        response = chat(
            model=MODEL, messages=history + [ask], tools=schemas, format=final_schema, options=OPTIONS
        )
        usage = [measure("conclude", response)]
        show([], usage)
        return {"answer": response.message.content, "usage": usage}

    def route(state: AgentState) -> str:
        """Arête conditionnelle : continuer l'enquête, réclamer une source, ou conclure."""
        if state["turns"] >= max_turns:
            return "conclude"
        if state["messages"][-1].get("tool_calls"):
            return "run_tools"
        if missing(state) and reminders(state) < MAX_REMINDERS:
            return "remind"
        return "conclude"

    def after_tools(state: AgentState) -> str:
        """Après les outils : rendre la main au modèle, ou conclure directement."""
        if direct_report and not missing(state):
            return "conclude"
        return "call_model"

    builder = StateGraph(AgentState)
    builder.add_node("call_model", call_model)
    builder.add_node("run_tools", run_tools)
    builder.add_node("remind", remind)
    builder.add_node("conclude", conclude)
    builder.add_edge(START, "call_model")
    builder.add_conditional_edges("call_model", route, ["run_tools", "remind", "conclude"])
    builder.add_conditional_edges("run_tools", after_tools, ["call_model", "conclude"])
    builder.add_edge("remind", "call_model")
    builder.add_edge("conclude", END)
    return builder.compile()


def run_agent(scenario: dict, system: str, user: str, **options) -> AgentState:
    """Lance un agent sur un scénario et renvoie son état final."""
    initial = {
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "turns": 0,
        "answer": None,
        "usage": [],
    }
    # Chaque tour traverse deux nœuds : on laisse à LangGraph la marge nécessaire.
    return build_agent(scenario, **options).invoke(initial, {"recursion_limit": 60})


def summarize(final: AgentState) -> dict:
    """Ce qu'un agent a fait et ce que ça a coûté, sous une forme facile à enregistrer."""
    messages = final["messages"]
    tool_messages = [m for m in messages if m["role"] == "tool"]
    return {
        # ce que l'agent a consulté et écrit : indispensable pour comprendre une erreur
        "consulted": consulted(messages),
        "reasoning": [m["content"] for m in messages if m["role"] == "assistant" and m.get("content")],
        "turns": final["turns"],
        "tool_calls": len(tool_messages),
        "tool_errors": sum(m["content"].startswith("ERREUR") for m in tool_messages),
        "hit_turn_limit": bool(messages[-1].get("tool_calls")),
        "model_calls": len(final["usage"]),
        "prompt_tokens": sum(u["prompt_tokens"] for u in final["usage"]),
        "output_tokens": sum(u["output_tokens"] for u in final["usage"]),
        "prompt_seconds": round(sum(u["prompt_seconds"] for u in final["usage"]), 1),
        "output_seconds": round(sum(u["output_seconds"] for u in final["usage"]), 1),
    }


# --- L'agent seul ------------------------------------------------------------------------

def diagnose(
    scenario: dict, chat=ollama.chat, brief: bool = False, aided: bool = False, trace: bool = False
) -> dict:
    """Lance l'agent seul sur un scénario et résume ce qui s'est passé.

    aided : True donne à l'agent seul les mêmes aides qu'à l'équipe (voir diagnose_aided).
    """
    if aided:
        return diagnose_aided(scenario, chat=chat, trace=trace)
    final = run_agent(
        scenario,
        system=system_prompt(brief),
        user=f"Ticket : {scenario['ticket']}",
        final_schema=diagnosis_schema(),
        final_ask=diagnosis_ask(),
        chat=chat,
        trace=trace,
    )
    return {"diagnosis": parse_diagnosis(final["answer"]), **summarize(final)}


def aided_schema() -> dict:
    """Le diagnostic, précédé d'un champ analysis où le modèle raisonne d'abord."""
    schema = diagnosis_schema()
    return {
        "type": "object",
        "properties": {"analysis": {"type": "string"}, **schema["properties"]},
        "required": ["analysis"] + schema["required"],
    }


def diagnose_aided(scenario: dict, chat=ollama.chat, trace: bool = False) -> dict:
    """L'agent seul, avec les trois aides dont dispose l'équipe.

    1. Couverture imposée : il doit consulter les 12 sources avant de conclure.
    2. Exigence de preuve : les mêmes repères que les agents de domaine.
    3. Analyse de périmètre : il déclare les cellules touchées, le code calcule les
       suspects et les innocentés, puis il rend son diagnostic en en tenant compte.
    Ce qui reste différent de l'équipe : un seul agent lit tout, dans un seul contexte.
    """
    cells = all_cells()
    cells_schema = {
        "type": "object",
        "properties": {"affected_cells": {"type": "array", "items": {"type": "string", "enum": cells}}},
        "required": ["affected_cells"],
    }
    cells_ask = (
        "Indique en JSON les cellules dont les mesures sont anormales pendant l'incident, sous"
        f" la forme {{\"affected_cells\": [...]}}. Cellules possibles : {', '.join(cells)}."
    )
    final = run_agent(
        scenario,
        system=system_prompt(aided=True),
        user=f"Ticket : {scenario['ticket']}",
        final_schema=cells_schema,
        final_ask=cells_ask,
        required=ALL_SOURCES,
        max_turns=2 * MAX_TURNS,
        chat=chat,
        trace=trace,
    )
    try:
        affected = [c for c in json.loads(final["answer"])["affected_cells"] if c in cells]
    except (json.JSONDecodeError, KeyError, TypeError):
        affected = []
    facts = scope_facts(affected, who="tu ne signales")

    # Deuxième et dernier appel : le diagnostic, avec l'analyse de périmètre sous les yeux.
    history = final["messages"]
    if history[-1].get("tool_calls"):
        history = history[:-1]
    choices = json.dumps(
        {key: value["enum"] for key, value in diagnosis_schema()["properties"].items()},
        ensure_ascii=False,
    )
    decide = "\n".join([
        facts,
        "",
        "Méthode :",
        "1. Un élément innocenté par l'analyse de périmètre ne peut pas être la cause : des"
        " cellules saines en dépendent, donc il fonctionne.",
        "2. Parmi les éléments suspects, retiens ceux pour lesquels tu as une preuve directe.",
        "3. S'il en reste plusieurs, la cause est le plus en amont, c'est-à-dire le dernier de"
        " la liste des suspects : sa panne explique les symptômes des éléments qui dépendent de"
        " lui, alors que l'inverse est impossible.",
        "4. S'il n'en reste aucun, choisis parmi les suspects celui qui paraît le plus"
        " directement défaillant.",
        "",
        "Donne ta conclusion finale en JSON avec exactement ces champs : analysis (ton"
        f" raisonnement en quelques phrases), domain, element, fault. Valeurs possibles : {choices}",
    ])
    messages = history + [
        {"role": "user", "content": cells_ask},
        {"role": "assistant", "content": final["answer"] or ""},
        {"role": "user", "content": decide},
    ]
    schemas, _ = make_tools(scenario)  # mêmes outils : le début du prompt reste en cache
    response = chat(model=MODEL, messages=messages, tools=schemas, format=aided_schema(), options=OPTIONS)
    usage = measure("decide", response)
    if trace:
        print(f"\n{facts}")
        print_usage(usage)
        print(f"analyse : {response.message.content}")
    final = {**final, "usage": final["usage"] + [usage]}
    return {"diagnosis": parse_diagnosis(response.message.content), **summarize(final)}


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        raise SystemExit(__doc__)
    scenario = load_scenario(args[0])
    print(f"=== {scenario['id']} ===\nTicket : {scenario['ticket']}\n")
    run = diagnose(
        scenario,
        brief="--brief-prompt" in sys.argv,
        aided="--aided" in sys.argv,
        trace=True,
    )
    print(f"\nDiagnostic structuré : {run['diagnosis']}")
    print(
        f"Coût : {run['model_calls']} appels au modèle, {run['tool_calls']} appels d'outils,"
        f" {run['prompt_tokens']} tokens lus, {run['output_tokens']} tokens écrits"
    )
    if run["hit_turn_limit"]:
        print("Plafond de tours atteint pendant l'enquête.")


if __name__ == "__main__":
    main()
