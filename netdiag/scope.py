"""Étape 2a : un premier graphe LangGraph, sans LLM.

Il automatise le raisonnement par périmètre :
  1. garder ce que les cellules en panne ont en commun ;
  2. retirer tout ce qu'une cellule saine utilise aussi.

Usage :
    python -m netdiag.scope --affected C3 --healthy C1 C2
"""

import argparse
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from netdiag.topology import all_cells, all_sites, cells_behind, path_to_core


class ScopeState(TypedDict):
    """L'état partagé : le dossier que les nœuds se passent."""

    affected: list[str]  # cellules en panne     (fourni en entrée)
    healthy: list[str]   # cellules saines       (fourni en entrée)
    common: list[str]    # écrit par find_common
    suspects: list[str]  # écrit par exonerate
    cleared: list[str]   # écrit par exonerate


# --- Les nœuds : des fonctions qui lisent l'état et renvoient ce qu'elles changent ---

def find_common(state: ScopeState) -> dict:
    """Nœud 1 : les éléments présents sur le chemin de TOUTES les cellules en panne."""
    paths = [path_to_core(cell) for cell in state["affected"]]
    common = [e for e in paths[0] if all(e in p for p in paths)]
    return {"common": common}


def exonerate(state: ScopeState) -> dict:
    """Nœud 2 : un élément utilisé par une cellule saine fonctionne forcément."""
    working = set()
    for cell in state["healthy"]:
        working.update(path_to_core(cell))
    return {
        "suspects": [e for e in state["common"] if e not in working],
        "cleared": [e for e in state["common"] if e in working],
    }


# --- Le graphe : on déclare les nœuds, puis les arêtes qui fixent l'ordre ---

def build_graph():
    builder = StateGraph(ScopeState)
    builder.add_node("find_common", find_common)
    builder.add_node("exonerate", exonerate)
    builder.add_edge(START, "find_common")
    builder.add_edge("find_common", "exonerate")
    builder.add_edge("exonerate", END)
    return builder.compile()


def scope_facts(affected_elements: list[str], who: str = "l'agent ran ne signale") -> str:
    """L'analyse de périmètre sous forme de texte, calculée par le code et non par le modèle.

    affected_elements : les cellules (ou sites) déclarés touchés. On garde ce que les
    cellules touchées ont en commun, puis on innocente tout ce qu'une cellule saine utilise.
    """
    affected = sorted(
        {e for e in affected_elements if e in all_cells()}
        | {cell for site in affected_elements if site in all_sites() for cell in cells_behind(site)}
    )
    if not affected:
        return f"Analyse de périmètre : impossible, {who} aucune cellule touchée."
    healthy = [cell for cell in all_cells() if cell not in affected]
    scope = build_graph().invoke({"affected": affected, "healthy": healthy})
    return "\n".join([
        "Analyse de périmètre (calculée à partir de la topologie, donc fiable) :",
        f"- cellules touchées : {', '.join(affected)} ; cellules saines : {', '.join(healthy) or 'aucune'}",
        f"- éléments suspects, de l'aval vers l'amont : {', '.join(scope['suspects'])}",
        f"- éléments innocentés : {', '.join(scope['cleared']) or 'aucun'}",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyse de périmètre d'une panne.")
    parser.add_argument("--affected", nargs="+", required=True, help="cellules en panne")
    parser.add_argument("--healthy", nargs="*", default=[], help="cellules saines")
    args = parser.parse_args()

    graph = build_graph()
    initial = {"affected": args.affected, "healthy": args.healthy}

    # stream(..., "updates") montre ce que chaque nœud a écrit dans l'état.
    for step in graph.stream(initial, stream_mode="updates"):
        for node, written in step.items():
            print(f"nœud {node:<12} a écrit : {written}")

    # invoke() exécute tout le graphe et renvoie l'état final complet.
    final = graph.invoke(initial)
    print("\nÉtat final :")
    for key, value in final.items():
        print(f"  {key:<9} {value}")


if __name__ == "__main__":
    main()
