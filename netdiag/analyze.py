"""Relit les fichiers de résultats et produit le tableau comparatif et l'analyse d'erreurs.

Ce module n'appelle aucun modèle : il ne fait que compter dans results/*.json.
Les tableaux principaux du README viennent d'ici.

Usage :
    python -m netdiag.analyze            # jeu de test
    python -m netdiag.analyze --split dev
"""

import argparse
import json

from netdiag.evaluate import FIELDS, RESULTS_DIR, SYSTEMS
from netdiag.scope import build_graph
from netdiag.topology import all_cells, all_sites, cells_behind

COMPARED = ["single", "single_aided", "team"]
NAMES = {"single": "agent seul", "single_aided": "agent seul aidé", "team": "équipe"}


def load_records(system: str, split: str) -> list[dict]:
    path = RESULTS_DIR / f"{SYSTEMS[system][1]}_{split}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["records"]


def is_network_wide(record: dict) -> bool:
    """Vrai si la panne attendue touche toutes les cellules (routeur, lien L3, cœur)."""
    return len(cells_behind(record["expected"]["element"])) == len(all_cells())


def ratio(records: list[dict], test) -> str:
    return f"{sum(test(r) for r in records)}/{len(records)}"


def mean(records: list[dict], value) -> str:
    return f"{sum(value(r) for r in records) / len(records):.1f}"


def sources(record: dict) -> int | None:
    """Nombre de sources distinctes consultées. None pour les premiers fichiers de
    résultats, enregistrés avant que cette information soit conservée."""
    return len(set(record["consulted"])) if "consulted" in record else None


def print_table(by_system: dict[str, list[dict]]) -> None:
    rows = [
        ("cause racine exacte", lambda rs: ratio(rs, lambda r: r["score"]["exact"])),
        *[(f"bon champ {field}", lambda rs, f=field: ratio(rs, lambda r: r["score"][f])) for field in FIELDS],
        ("pannes locales", lambda rs: ratio([r for r in rs if not is_network_wide(r)], lambda r: r["score"]["exact"])),
        ("pannes sur tout le réseau", lambda rs: ratio([r for r in rs if is_network_wide(r)], lambda r: r["score"]["exact"])),
        ("sources lues sur 12", lambda rs: mean(rs, sources) if sources(rs[0]) is not None else "non mesuré"),
        ("exécutions à 12 sources", lambda rs: ratio(rs, lambda r: sources(r) == 12) if sources(rs[0]) is not None else "non mesuré"),
        ("appels au modèle", lambda rs: mean(rs, lambda r: r["model_calls"])),
        ("tokens lus", lambda rs: mean(rs, lambda r: r["prompt_tokens"])),
        ("tokens écrits", lambda rs: mean(rs, lambda r: r["output_tokens"])),
    ]
    print(f"{'':<27}" + "".join(f"{NAMES[s]:>18}" for s in by_system))
    for label, compute in rows:
        print(f"{label:<27}" + "".join(f"{compute(rs):>18}" for rs in by_system.values()))


def scope_of(report: dict) -> dict:
    """L'analyse de périmètre telle que l'orchestrateur l'a reçue pour ce rapport ran."""
    listed = report["affected_elements"]
    affected = sorted(
        {e for e in listed if e in all_cells()}
        | {cell for site in listed if site in all_sites() for cell in cells_behind(site)}
    )
    if not affected:
        return {"suspects": [], "cleared": []}
    healthy = [cell for cell in all_cells() if cell not in affected]
    return build_graph().invoke({"affected": affected, "healthy": healthy})


def rules_by_code(record: dict) -> dict | None:
    """Ce qu'auraient donné les règles de l'orchestrateur appliquées par le code.

    Règles 1 à 3 de team.orchestrator_prompt : parmi les suspects, garder ceux qu'un agent
    désigne comme cause locale, puis prendre le plus en amont. Calcul fait APRÈS la mesure,
    sur les rapports enregistrés : c'est une piste, pas un résultat du système.
    """
    reports = record["reports"]
    suspects = scope_of(next(r for r in reports if r["domain"] == "ran"))["suspects"]
    claims = [r for r in reports if r["status"] == "local_cause" and r["element"] in suspects]
    if not claims:
        return None
    chosen = max(claims, key=lambda r: suspects.index(r["element"]))
    return {"domain": chosen["domain"], "element": chosen["element"], "fault": chosen["fault"]}


def print_team_analysis(records: list[dict]) -> None:
    print("\nÉquipe : d'où viennent les erreurs ?")
    print(f"{'scénario':<9}{'résultat':<9}{'le bon agent avait la cause':<29}{'se déclarent cause':<34}choix de l'orchestrateur")
    found = outside = overclaims = others = by_code = 0
    for r in records:
        expected, reports = r["expected"], r["reports"]
        own = next(x for x in reports if x["domain"] == expected["domain"])
        has_it = own["status"] == "local_cause" and (own["element"], own["fault"]) == (expected["element"], expected["fault"])
        claims = [x for x in reports if x["status"] == "local_cause"]
        suspects = scope_of(next(x for x in reports if x["domain"] == "ran"))["suspects"]
        chosen = r["diagnosis"]["element"] if r["diagnosis"] else "aucun"
        off_list = bool(suspects) and chosen not in suspects
        found += has_it
        outside += off_list
        overclaims += sum(x["domain"] != expected["domain"] for x in claims)
        others += sum(x["domain"] != expected["domain"] for x in reports)
        by_code += rules_by_code(r) == expected
        print(
            f"{r['scenario']:<9}{'OK' if r['score']['exact'] else 'ERREUR':<9}{'oui' if has_it else 'non':<29}"
            f"{', '.join(x['element'] for x in claims) or 'personne':<34}{chosen}"
            + (" (hors de la liste des suspects)" if off_list else "")
        )
    n = len(records)
    print(f"\nLe spécialiste du domaine fautif avait écrit la cause exacte : {found}/{n}")
    print(f"L'orchestrateur a rendu la cause exacte : {sum(r['score']['exact'] for r in records)}/{n}")
    print(f"L'orchestrateur a choisi un élément hors de la liste des suspects : {outside}/{n}")
    print(f"Rapports d'un domaine non fautif qui se déclarent cause locale : {overclaims}/{others}")
    print(f"Règles d'arbitrage appliquées par le code sur ces mêmes rapports (calcul après coup) : {by_code}/{n}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Tableau comparatif et analyse d'erreurs.")
    parser.add_argument("--split", choices=["dev", "test"], default="test")
    args = parser.parse_args()

    by_system = {s: load_records(s, args.split) for s in COMPARED}
    by_system = {s: records for s, records in by_system.items() if records}
    if not by_system:
        raise SystemExit(f"Aucun résultat pour le jeu {args.split} dans {RESULTS_DIR}.")
    print(f"Jeu {args.split} : {len(next(iter(by_system.values())))} scénarios, moyennes par exécution\n")
    print_table(by_system)
    if "team" in by_system:
        print_team_analysis(by_system["team"])


if __name__ == "__main__":
    main()
