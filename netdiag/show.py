"""Affiche un scénario comme le verrait un technicien : ticket, chronologie, mesures.

Usage :
    python -m netdiag.show SC01            # sans la réponse
    python -m netdiag.show SC01 --answer   # avec la cause racine attendue
"""

import sys

from netdiag.scenarios import load_ground_truth, load_scenario, timeline


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        raise SystemExit(__doc__)
    scenario = load_scenario(args[0])

    print(f"=== {scenario['id']} ===")
    print(f"Ticket : {scenario['ticket']}\n")

    print("Chronologie (tous domaines confondus)")
    print(f"{'heure':<9} {'domaine':<10} {'élément':<8} {'type':<7} détail")
    for e in timeline(scenario):
        print(f"{e['time']:<9} {e['domain']:<10} {e['element']:<8} {e['kind']:<7} {e['detail']}")

    print("\nMesures (avant la panne -> pendant la panne)")
    print(f"{'domaine':<10} {'élément':<8} {'mesure':<28} {'avant':>7} {'pendant':>8}")
    for k in scenario["kpis"]:
        print(f"{k['domain']:<10} {k['element']:<8} {k['name']:<28} {k['before']:>7} {k['during']:>8}")

    if "--answer" in sys.argv:
        truth = load_ground_truth()[scenario["id"]]
        print(f"\nCause racine attendue : {truth['domain']} / {truth['element']} / {truth['fault']}")


if __name__ == "__main__":
    main()
