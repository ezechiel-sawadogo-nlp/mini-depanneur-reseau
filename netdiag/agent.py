"""Un agent seul, qui enquête par appels d'outils puis rend un diagnostic structuré.

    START -> call_model -> (outils demandés ?) -> run_tools -> call_model -> ...
                        -> (sinon)             -> conclude  -> END

Usage :
    python -m netdiag.agent SC01
"""

import json
import operator
import sys
from typing import Annotated, TypedDict

import ollama
from langgraph.graph import END, START, StateGraph

from netdiag.scenarios import load_network, load_scenario
from netdiag.tools import DOMAINS, make_tools, run_tool

MODEL = "qwen2.5:7b"
MAX_TURNS = 8  # nombre maximal d'appels au modèle pendant l'enquête
# temperature 0 : réponses reproductibles. num_ctx : taille de la fenêtre de contexte.
OPTIONS = {"temperature": 0, "num_ctx": 8192}


class AgentState(TypedDict):
    # Annotated[..., operator.add] est un "reducer" : ce qu'un nœud renvoie pour
    # cette clé est AJOUTÉ à la liste existante au lieu de la remplacer.
    messages: Annotated[list[dict], operator.add]
    turns: int  # pas de reducer : la nouvelle valeur remplace l'ancienne
    diagnosis: dict | None  # écrit par le nœud conclude


def system_prompt() -> str:
    """Les consignes et la description du réseau, construites depuis network.json."""
    net = load_network()
    lines = [
        "Tu es un agent de diagnostic d'un réseau mobile. On te donne un ticket d'incident.",
        "Trouve la cause racine : l'événement initial qui explique tous les symptômes.",
        "",
        "Réseau :",
    ]
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
    lines += [
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
        "Quand tu as assez d'éléments, n'appelle plus d'outil et donne ta conclusion :"
        " domaine, élément, type de panne (dans la liste ci-dessus) et la preuve principale.",
    ]
    return "\n".join(lines)


def diagnosis_schema() -> dict:
    """Le format imposé à la réponse finale : trois champs, chacun dans une liste fermée."""
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


def parse_diagnosis(text: str) -> dict | None:
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


def build_agent(scenario: dict, chat=ollama.chat, allowed_domains: list[str] = DOMAINS):
    """Construit le graphe de l'agent pour un scénario.

    chat : la fonction qui appelle le modèle. Par défaut Ollama ; dans les tests,
    on la remplace par une fausse fonction pour vérifier le graphe sans LLM.
    """
    schemas, functions = make_tools(scenario, allowed_domains)

    def call_model(state: AgentState) -> dict:
        """Nœud 1 : le modèle lit tout l'historique et décide de la suite."""
        response = chat(model=MODEL, messages=state["messages"], tools=schemas, options=OPTIONS)
        message = response.message.model_dump(exclude_none=True)
        return {"messages": [message], "turns": state["turns"] + 1}

    def run_tools(state: AgentState) -> dict:
        """Nœud 2 : notre code exécute chaque outil demandé par le modèle."""
        results = []
        for call in state["messages"][-1]["tool_calls"]:
            name = call["function"]["name"]
            arguments = call["function"]["arguments"]
            content = run_tool(functions, name, arguments)
            results.append({"role": "tool", "tool_name": name, "content": content})
        return {"messages": results}

    def conclude(state: AgentState) -> dict:
        """Nœud 3 : un dernier appel, sans outils, dont la réponse est contrainte au schéma."""
        history = state["messages"]
        if history[-1].get("tool_calls"):
            # plafond atteint : on retire la demande d'outils restée sans réponse
            history = history[:-1]
        schema = diagnosis_schema()
        ask = {
            "role": "user",
            "content": "Donne maintenant ta conclusion finale en JSON, avec exactement ces champs"
            f" et ces valeurs possibles : {json.dumps(schema['properties'], ensure_ascii=False)}",
        }
        response = chat(model=MODEL, messages=history + [ask], format=schema, options=OPTIONS)
        return {"diagnosis": parse_diagnosis(response.message.content)}

    def route(state: AgentState) -> str:
        """Arête conditionnelle : continuer l'enquête ou passer à la conclusion."""
        last = state["messages"][-1]
        if last.get("tool_calls") and state["turns"] < MAX_TURNS:
            return "run_tools"
        return "conclude"

    builder = StateGraph(AgentState)
    builder.add_node("call_model", call_model)
    builder.add_node("run_tools", run_tools)
    builder.add_node("conclude", conclude)
    builder.add_edge(START, "call_model")
    builder.add_conditional_edges("call_model", route, ["run_tools", "conclude"])
    builder.add_edge("run_tools", "call_model")
    builder.add_edge("conclude", END)
    return builder.compile()


def initial_state(scenario: dict) -> AgentState:
    return {
        "messages": [
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": f"Ticket : {scenario['ticket']}"},
        ],
        "turns": 0,
        "diagnosis": None,
    }


def diagnose(scenario: dict, chat=ollama.chat) -> dict:
    """Lance l'agent sur un scénario et résume ce qui s'est passé."""
    final = build_agent(scenario, chat=chat).invoke(initial_state(scenario))
    tool_messages = [m for m in final["messages"] if m["role"] == "tool"]
    return {
        "diagnosis": final["diagnosis"],
        "turns": final["turns"],
        "tool_calls": len(tool_messages),
        "tool_errors": sum(m["content"].startswith("ERREUR") for m in tool_messages),
        "hit_turn_limit": bool(final["messages"][-1].get("tool_calls")),
    }


def print_message(message: dict) -> None:
    """Affiche un message de l'historique sous forme de trace lisible."""
    if message["role"] == "tool":
        print(f"  [outil] {message['tool_name']} a renvoyé :")
        for line in message["content"].splitlines():
            print(f"      {line}")
    elif message.get("tool_calls"):
        for call in message["tool_calls"]:
            args = ", ".join(f"{k}={v!r}" for k, v in call["function"]["arguments"].items())
            print(f"[modèle] demande {call['function']['name']}({args})")
    else:
        print(f"[modèle] raisonnement :\n{message.get('content', '')}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    scenario = load_scenario(sys.argv[1])
    graph = build_agent(scenario)

    print(f"=== {scenario['id']} ===\nTicket : {scenario['ticket']}\n")
    turns = 0
    for step in graph.stream(initial_state(scenario), stream_mode="updates"):
        for written in step.values():
            turns = written.get("turns", turns)
            for message in written.get("messages", []):
                print_message(message)
            if "diagnosis" in written:
                print(f"\nDiagnostic structuré : {written['diagnosis']}")

    print(f"Appels au modèle pendant l'enquête : {turns} (maximum {MAX_TURNS})")


if __name__ == "__main__":
    main()
