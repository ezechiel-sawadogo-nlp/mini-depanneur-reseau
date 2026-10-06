"""Les outils de consultation des données d'un scénario.

Un outil = une fonction Python + un schéma JSON qui la décrit au modèle.
Les outils ne lisent que le scénario : jamais la vérité terrain.
"""

DOMAINS = ["ran", "transport", "core"]

_DESCRIPTIONS = {
    "get_alarms": "Alarmes actives d'un domaine : heure, élément, nom, gravité.",
    "get_kpis": "Mesures de performance (KPI) d'un domaine : valeur avant et pendant l'incident.",
    "get_logs": "Lignes de log des équipements d'un domaine, avec leur heure.",
    "get_config_changes": "Changements de configuration récents dans un domaine, avec leur heure.",
}


def _schema(name: str, allowed_domains: list[str]) -> dict:
    """Le schéma JSON envoyé au modèle. 'enum' ferme la liste des valeurs permises."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": _DESCRIPTIONS[name],
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "enum": allowed_domains,
                        "description": "Le domaine du réseau à consulter.",
                    }
                },
                "required": ["domain"],
            },
        },
    }


def make_tools(scenario: dict, allowed_domains: list[str] = DOMAINS) -> tuple[list[dict], dict]:
    """Fabrique les outils d'un agent pour un scénario donné.

    allowed_domains : les domaines que cet agent a le droit de consulter.
    Renvoie (schémas pour le modèle, table nom -> fonction).
    Le scénario est fixé ici : le modèle choisit le domaine, jamais le scénario.
    """

    def rows(kind: str, domain: str) -> list[dict]:
        if domain not in allowed_domains:
            raise ValueError(
                f"domaine invalide ou non autorisé : {domain!r}. "
                f"Valeurs possibles : {allowed_domains}"
            )
        return [r for r in scenario[kind] if r["domain"] == domain]

    def get_alarms(domain: str) -> str:
        found = rows("alarms", domain)
        if not found:
            return f"Aucune alarme active dans le domaine {domain}."
        return "\n".join(
            f"{a['time']} {a['element']} {a['name']} ({a['severity']})" for a in found
        )

    def get_kpis(domain: str) -> str:
        found = rows("kpis", domain)
        if not found:
            return f"Aucune mesure disponible dans le domaine {domain}."
        return "\n".join(
            f"{k['element']} {k['name']} : avant {k['before']}, pendant {k['during']}"
            for k in found
        )

    def get_logs(domain: str) -> str:
        found = rows("logs", domain)
        if not found:
            return f"Aucun log dans le domaine {domain}."
        return "\n".join(f"{l['time']} {l['element']} : {l['message']}" for l in found)

    def get_config_changes(domain: str) -> str:
        found = rows("config_changes", domain)
        if not found:
            return f"Aucun changement de configuration récent dans le domaine {domain}."
        return "\n".join(f"{c['time']} {c['element']} : {c['description']}" for c in found)

    functions = {
        "get_alarms": get_alarms,
        "get_kpis": get_kpis,
        "get_logs": get_logs,
        "get_config_changes": get_config_changes,
    }
    schemas = [_schema(name, allowed_domains) for name in functions]
    return schemas, functions


def run_tool(functions: dict, name: str, arguments: dict) -> str:
    """Exécute un appel d'outil demandé par le modèle.

    Ne lève jamais d'exception : une erreur devient un texte commençant par
    'ERREUR', que le modèle lit et peut corriger au tour suivant.
    """
    if name not in functions:
        return f"ERREUR : outil inconnu {name!r}. Outils disponibles : {sorted(functions)}"
    try:
        return functions[name](**arguments)
    except (TypeError, ValueError) as exc:
        return f"ERREUR : {exc}"
