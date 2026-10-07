"""Chargement des scénarios de panne et de la vérité terrain.

Règle du projet : la vérité terrain n'est lue que par l'évaluation.
Aucun agent ni aucun outil ne doit appeler load_ground_truth().
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _read_json(path: Path) -> dict:
    # encoding explicite : sous Windows, l'encodage par défaut n'est pas UTF-8.
    return json.loads(path.read_text(encoding="utf-8"))


def load_network() -> dict:
    """Le réseau fictif : domaines, éléments, dépendances, types de panne."""
    return _read_json(DATA_DIR / "network.json")


def list_scenario_ids(split: str = "all") -> list[str]:
    """Les identifiants des scénarios : tous, ou seulement ceux d'un sous-ensemble.

    split : "all", "dev" (mise au point du système) ou "test" (notation finale).
    """
    if split == "all":
        return sorted(p.stem for p in (DATA_DIR / "scenarios").glob("*.json"))
    return _read_json(DATA_DIR / "splits.json")[split]


def load_scenario(scenario_id: str) -> dict:
    """Ce que le système de dépannage a le droit de voir pour un scénario."""
    path = DATA_DIR / "scenarios" / f"{scenario_id}.json"
    if not path.exists():
        raise ValueError(
            f"scénario inconnu : {scenario_id}. Disponibles : {list_scenario_ids()}"
        )
    return _read_json(path)


def load_ground_truth() -> dict:
    """La cause racine attendue de chaque scénario. Réservé à l'évaluation."""
    return _read_json(DATA_DIR / "ground_truth.json")


def timeline(scenario: dict) -> list[dict]:
    """Alarmes, changements de configuration et logs, fusionnés et triés par heure.

    Chaque événement devient un dictionnaire : time, domain, element, kind, detail.
    """
    events = []
    for a in scenario["alarms"]:
        events.append({**a, "kind": "ALARME", "detail": f"{a['name']} ({a['severity']})"})
    for c in scenario["config_changes"]:
        events.append({**c, "kind": "CONFIG", "detail": c["description"]})
    for log in scenario["logs"]:
        events.append({**log, "kind": "LOG", "detail": log["message"]})
    # Les heures sont au format HH:MM:SS : le tri alphabétique est aussi chronologique.
    return sorted(events, key=lambda e: e["time"])
