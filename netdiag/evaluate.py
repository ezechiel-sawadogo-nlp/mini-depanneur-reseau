"""Évaluation : l'agent trouve-t-il la bonne cause racine ?

C'est le seul module autorisé à lire la vérité terrain.

Usage :
    python -m netdiag.evaluate
"""

import json
import time
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


def main() -> None:
    truth = load_ground_truth()
    records = []

    for scenario_id in list_scenario_ids():
        start = time.perf_counter()
        run = diagnose(load_scenario(scenario_id))
        seconds = round(time.perf_counter() - start, 1)
        record = {
            "scenario": scenario_id,
            "expected": truth[scenario_id],
            **run,
            "score": score(run["diagnosis"], truth[scenario_id]),
            "seconds": seconds,
        }
        records.append(record)
        verdict = "OK    " if record["score"]["exact"] else "ERREUR"
        print(
            f"{scenario_id}  {verdict}  attendu : {label(truth[scenario_id]):<32}"
            f" prédit : {label(run['diagnosis']):<32}"
            f" outils : {run['tool_calls']:>2}  durée : {seconds:>5} s"
        )

    n = len(records)
    print(f"\nRésultats sur {n} scénarios ({MODEL}, agent seul)")
    for field in ("exact",) + FIELDS:
        good = sum(r["score"][field] for r in records)
        print(f"  {field:<8} {good}/{n}")
    print(f"  appels d'outils en erreur : {sum(r['tool_errors'] for r in records)}")
    print(f"  plafond de tours atteint  : {sum(r['hit_turn_limit'] for r in records)}")

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / "single_agent.json"
    out.write_text(
        json.dumps({"model": MODEL, "records": records}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nDétail enregistré dans {out.relative_to(RESULTS_DIR.parent)}")


if __name__ == "__main__":
    main()
