"""Évaluation : l'agent trouve-t-il la bonne cause racine ?

C'est le seul module autorisé à lire la vérité terrain.

Usage :
    python -m netdiag.evaluate
    python -m netdiag.evaluate --repeats 3 --prompt brief   # variante écartée
"""

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from netdiag.agent import MODEL, diagnose
from netdiag.scenarios import list_scenario_ids, load_ground_truth, load_scenario

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
FIELDS = ("domain", "element", "fault")


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


def run_all(repeats: int, brief: bool) -> list[dict]:
    """Exécute chaque scénario 'repeats' fois et renvoie un enregistrement par exécution.

    On alterne les scénarios (SC01, SC02, SC03, SC01, ...) au lieu de répéter le même
    trois fois de suite : les conditions d'exécution varient comme en usage réel.
    """
    truth = load_ground_truth()
    records = []
    for repeat in range(1, repeats + 1):
        for scenario_id in list_scenario_ids():
            start = time.perf_counter()
            run = diagnose(load_scenario(scenario_id), brief=brief)
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
                flush=True,
            )
    return records


def print_summary(records: list[dict], repeats: int, prompt: str) -> None:
    truth = load_ground_truth()
    n = len(records)
    print(f"\nRésumé : {MODEL}, agent seul, prompt {prompt}, {repeats} répétition(s)")
    print(f"{'scénario':<9} {'réussites':<10} détail")
    for scenario_id in list_scenario_ids():
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
    for key, text in (
        ("model_calls", "appels au modèle"),
        ("tool_calls", "appels d'outils"),
        ("prompt_tokens", "tokens lus"),
        ("output_tokens", "tokens écrits"),
        ("seconds", "secondes"),
    ):
        print(f"  {text:<17} {sum(r[key] for r in records) / n:.1f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Évalue l'agent seul sur tous les scénarios.")
    parser.add_argument("--repeats", type=int, default=1, help="exécutions par scénario")
    parser.add_argument("--prompt", choices=["verbose", "brief"], default="verbose")
    args = parser.parse_args()

    records = run_all(args.repeats, brief=args.prompt == "brief")
    print_summary(records, args.repeats, args.prompt)

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"single_agent_{args.prompt}.json"
    payload = {"model": MODEL, "prompt": args.prompt, "repeats": args.repeats, "records": records}
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nDétail enregistré dans {out.relative_to(RESULTS_DIR.parent)}")


if __name__ == "__main__":
    main()
