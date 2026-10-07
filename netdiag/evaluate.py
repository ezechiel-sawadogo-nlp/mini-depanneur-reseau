"""Évaluation : le système trouve-t-il la bonne cause racine ?

C'est le seul module autorisé à lire la vérité terrain.

Usage :
    python -m netdiag.evaluate                          # agent seul, scénarios dev
    python -m netdiag.evaluate --system single_aided    # agent seul avec les aides de l'équipe
    python -m netdiag.evaluate --system team            # équipe multi-agents, scénarios dev
    python -m netdiag.evaluate --system team --split test   # notation finale, une seule fois
"""

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from netdiag.agent import MODEL, diagnose
from netdiag.team import diagnose_team
from netdiag.scenarios import list_scenario_ids, load_ground_truth, load_scenario

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
FIELDS = ("domain", "element", "fault")

# Les systèmes comparés : un nom, la fonction qui diagnostique un scénario, le fichier de résultats.
SYSTEMS = {
    "single": (lambda scenario: diagnose(scenario), "single_agent_verbose"),
    "single_aided": (lambda scenario: diagnose(scenario, aided=True), "single_agent_aided"),
    "single_brief": (lambda scenario: diagnose(scenario, brief=True), "single_agent_brief"),
    "team": (lambda scenario: diagnose_team(scenario), "team"),
}


def score(predicted: dict | None, expected: dict) -> dict:
    """Compare un diagnostic à la vérité terrain, champ par champ.

    'exact' vaut True seulement si les trois champs sont justes.
    Un diagnostic absent ou illisible (None) compte comme une erreur.
    """
    result = {f: predicted is not None and predicted[f] == expected[f] for f in FIELDS}
    result["exact"] = all(result[f] for f in FIELDS)
    return result


def label(diagnosis: dict | None) -> str:
    if diagnosis is None:
        return "(aucun diagnostic)"
    return " / ".join(diagnosis[f] for f in FIELDS)


def run_all(scenario_ids: list[str], repeats: int, run_one, save=None) -> list[dict]:
    """Exécute chaque scénario 'repeats' fois et renvoie un enregistrement par exécution.

    On alterne les scénarios (SC01, SC02, SC03, SC01, ...) au lieu de répéter le même
    trois fois de suite : les conditions d'exécution varient comme en usage réel.
    save : fonction appelée après chaque exécution avec les enregistrements déjà obtenus,
    pour ne rien perdre si une longue série est interrompue.
    """
    truth = load_ground_truth()
    records = []
    for repeat in range(1, repeats + 1):
        for scenario_id in scenario_ids:
            start = time.perf_counter()
            run = run_one(load_scenario(scenario_id))
            seconds = round(time.perf_counter() - start, 1)
            record = {
                "scenario": scenario_id,
                "repeat": repeat,
                "expected": truth[scenario_id],
                **run,
                "score": score(run["diagnosis"], truth[scenario_id]),
                "seconds": seconds,
            }
            records.append(record)
            verdict = "OK    " if record["score"]["exact"] else "ERREUR"
            print(
                f"{scenario_id} n°{repeat}  {verdict}  prédit : {label(run['diagnosis']):<30}"
                f" outils : {run['tool_calls']:>2}  durée : {seconds:>5} s"
                f"  tokens lus/écrits : {run['prompt_tokens']}/{run['output_tokens']}",
            )
            print(f"          consulté : {', '.join(run['consulted']) or 'rien'}", flush=True)
            if save:
                save(records)
    return records


def print_summary(records: list[dict], title: str) -> None:
    truth = load_ground_truth()
    n = len(records)
    print(f"\nRésumé : {title}")
    print(f"{'scénario':<9} {'réussites':<10} détail")
    for scenario_id in sorted({r["scenario"] for r in records}):
        runs = [r for r in records if r["scenario"] == scenario_id]
        good = sum(r["score"]["exact"] for r in runs)
        counts = Counter(label(r["diagnosis"]) for r in runs)
        seen = ", ".join(f"{text} x{count}" for text, count in counts.most_common())
        print(f"{scenario_id:<9} {good}/{len(runs):<8} attendu {label(truth[scenario_id])} | {seen}")

    print(f"\nSur {n} exécutions :")
    for field in ("exact",) + FIELDS:
        good = sum(r["score"][field] for r in records)
        print(f"  {field:<8} {good}/{n} ({100 * good / n:.0f} %)")
    print(f"  appels d'outils en erreur : {sum(r['tool_errors'] for r in records)}")
    print(f"  plafond de tours atteint  : {sum(r['hit_turn_limit'] for r in records)}")
    print("Moyennes par exécution :")
    sources = sum(len(set(r["consulted"])) for r in records) / n
    print(f"  {'sources lues':<17} {sources:.1f} sur 12")
    for key, text in (
        ("model_calls", "appels au modèle"),
        ("tool_calls", "appels d'outils"),
        ("prompt_tokens", "tokens lus"),
        ("output_tokens", "tokens écrits"),
        ("seconds", "secondes"),
    ):
        print(f"  {text:<17} {sum(r[key] for r in records) / n:.1f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Évalue un système sur un jeu de scénarios.")
    parser.add_argument("--system", choices=list(SYSTEMS), default="single")
    parser.add_argument("--repeats", type=int, default=1, help="exécutions par scénario")
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev",
                        help="dev : mise au point ; test : notation finale")
    args = parser.parse_args()

    run_one, file_stem = SYSTEMS[args.system]
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{file_stem}_{args.split}.json"

    def save(records: list[dict]) -> None:
        payload = {"model": MODEL, "system": args.system, "split": args.split,
                   "repeats": args.repeats, "records": records}
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    records = run_all(list_scenario_ids(args.split), args.repeats, run_one, save)
    title = f"{MODEL}, système {args.system}, scénarios {args.split}, {args.repeats} répétition(s)"
    print_summary(records, title)
    print(f"\nDétail enregistré dans {out.relative_to(RESULTS_DIR.parent)}")


if __name__ == "__main__":
    main()
