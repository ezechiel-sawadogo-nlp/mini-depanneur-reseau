"""Un agent seul, qui enquête par appels d'outils puis rend un diagnostic structuré.

    START -> call_model -> (outils demandés ?) -> run_tools -> call_model -> ...
                        -> (sinon)             -> conclude  -> END

Usage :
    python -m netdiag.agent SC01
    python -m netdiag.agent SC01 --brief-prompt   # variante avec consigne de brièveté
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
    usage: Annotated[list[dict], operator.add]  # une mesure par appel au modèle


def system_prompt(brief: bool = False) -> str:
    """Les consignes et la description du réseau, construites depuis network.json.

    brief : True ajoute une consigne de brièveté. Mesuré sur 3 scénarios x 3 exécutions :
    2,3 fois plus rapide, mais 3 diagnostics justes sur 9 contre 9 sur 9 sans elle.
    La variante est conservée pour pouvoir refaire la comparaison ; elle n'est pas utilisée.
    """
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
        return {
            "messages": [message],
            "turns": state["turns"] + 1,
            "usage": [measure("call_model", response)],
        }

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
        # On repasse les mêmes outils : le début du prompt reste identique aux appels
        # précédents, donc Ollama réutilise son cache au lieu de tout relire.
        response = chat(
            model=MODEL, messages=history + [ask], tools=schemas, format=schema, options=OPTIONS
        )
        return {
            "diagnosis": parse_diagnosis(response.message.content),
            "usage": [measure("conclude", response)],
        }

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


def initial_state(scenario: dict, brief: bool = False) -> AgentState:
    return {
        "messages": [
            {"role": "system", "content": system_prompt(brief)},
            {"role": "user", "content": f"Ticket : {scenario['ticket']}"},
        ],
        "turns": 0,
        "diagnosis": None,
        "usage": [],
    }


def diagnose(scenario: dict, chat=ollama.chat, brief: bool = False) -> dict:
    """Lance l'agent sur un scénario et résume ce qui s'est passé."""
    final = build_agent(scenario, chat=chat).invoke(initial_state(scenario, brief))
    tool_messages = [m for m in final["messages"] if m["role"] == "tool"]
    assistant_messages = [m for m in final["messages"] if m["role"] == "assistant"]
    return {
        "diagnosis": final["diagnosis"],
        # ce que l'agent a consulté, dans l'ordre, sous la forme "alarms:ran"
        "consulted": [
            f"{call['function']['name'].removeprefix('get_')}:{call['function']['arguments'].get('domain', '?')}"
            for m in assistant_messages
            for call in m.get("tool_calls") or []
        ],
        # ce que l'agent a écrit : indispensable pour comprendre une erreur après coup
        "reasoning": [m["content"] for m in assistant_messages if m.get("content")],
        "turns": final["turns"],
        "tool_calls": len(tool_messages),
        "tool_errors": sum(m["content"].startswith("ERREUR") for m in tool_messages),
        "hit_turn_limit": bool(final["messages"][-1].get("tool_calls")),
        "model_calls": len(final["usage"]),
        "prompt_tokens": sum(u["prompt_tokens"] for u in final["usage"]),
        "output_tokens": sum(u["output_tokens"] for u in final["usage"]),
        "prompt_seconds": round(sum(u["prompt_seconds"] for u in final["usage"]), 1),
        "output_seconds": round(sum(u["output_seconds"] for u in final["usage"]), 1),
    }


def print_message(message: dict) -> None:
    """Affiche un message de l'historique sous forme de trace lisible."""
    if message["role"] == "tool":
        print(f"  [outil] {message['tool_name']} a renvoyé :")
        for line in message["content"].splitlines():
            print(f"      {line}")
    elif message.get("tool_calls"):
        if message.get("content"):
            print(f"[modèle] {message['content']}")
        for call in message["tool_calls"]:
            args = ", ".join(f"{k}={v!r}" for k, v in call["function"]["arguments"].items())
            print(f"[modèle] demande {call['function']['name']}({args})")
    else:
        print(f"[modèle] raisonnement :\n{message.get('content', '')}")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        raise SystemExit(__doc__)
    brief = "--brief-prompt" in sys.argv
    scenario = load_scenario(args[0])
    graph = build_agent(scenario)

    print(f"=== {scenario['id']} ===\nTicket : {scenario['ticket']}\n")
    turns = 0
    usage = []
    for step in graph.stream(initial_state(scenario, brief), stream_mode="updates"):
        for written in step.values():
            turns = written.get("turns", turns)
            for message in written.get("messages", []):
                print_message(message)
            if "diagnosis" in written:
                print(f"\nDiagnostic structuré : {written['diagnosis']}")
            for u in written.get("usage", []):
                usage.append(u)
                print(
                    f"  [mesure] {u['node']:<10} {u['prompt_tokens']:>5} tokens lus en"
                    f" {u['prompt_seconds']:>5} s, {u['output_tokens']:>4} tokens écrits en"
                    f" {u['output_seconds']:>5} s"
                )

    print(f"\nAppels au modèle pendant l'enquête : {turns} (maximum {MAX_TURNS})")
    print(
        f"Total : {sum(u['prompt_tokens'] for u in usage)} tokens lus en"
        f" {sum(u['prompt_seconds'] for u in usage):.1f} s,"
        f" {sum(u['output_tokens'] for u in usage)} tokens écrits en"
        f" {sum(u['output_seconds'] for u in usage):.1f} s"
    )


if __name__ == "__main__":
    main()
