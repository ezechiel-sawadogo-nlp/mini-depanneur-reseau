"""Etape 0 : verifier que le modele local sait demander un appel d'outil.

Lancement :  python scripts/00_check_tool_calling.py
Prerequis :  Ollama demarre, modele qwen2.5:7b telecharge.
"""

import ollama

MODEL = "qwen2.5:7b"


def get_alarms(domain: str) -> str:
    """Retourne les alarmes actives d'un domaine du reseau.

    Args:
        domain: le domaine a interroger, parmi "ran", "transport", "core".
    """
    # Donnees en dur pour ce test. A l'etape 1, elles viendront des scenarios.
    fake_alarms = {
        "ran": "CELL_DOWN sur la cellule C1 (site S1), critique, 10:02",
        "transport": "LINK_DOWN sur le lien L1 (site S1 vers routeur R1), critique, 10:01",
        "core": "aucune alarme",
    }
    return fake_alarms.get(domain, f"domaine inconnu : {domain}")


# Table nom -> fonction : c'est NOTRE code qui execute l'outil, pas le modele.
TOOLS = {"get_alarms": get_alarms}

messages = [
    {
        "role": "user",
        "content": "Quelles sont les alarmes actives dans le domaine transport ?",
    }
]

# --- Appel 1 : le modele decide s'il a besoin d'un outil -------------------
response = ollama.chat(
    model=MODEL,
    messages=messages,
    tools=[get_alarms],  # la bibliotheque transforme la fonction en schema JSON
    options={"temperature": 0},
)

print("=== Appel 1 : ce que le modele renvoie ===")
print("texte      :", repr(response.message.content))
print("tool_calls :", response.message.tool_calls)

if not response.message.tool_calls:
    raise SystemExit(
        "\nECHEC : le modele a repondu en texte sans demander d'outil."
    )

# --- Notre code execute chaque outil demande --------------------------------
messages.append(response.message)  # on garde la demande dans l'historique

for call in response.message.tool_calls:
    name = call.function.name
    args = call.function.arguments
    result = TOOLS[name](**args)
    print(f"\n=== Execution par notre code : {name}({args}) ===")
    print("resultat   :", result)
    messages.append({"role": "tool", "tool_name": name, "content": result})

# --- Appel 2 : le modele redige sa reponse a partir du resultat -------------
final = ollama.chat(
    model=MODEL,
    messages=messages,
    tools=[get_alarms],
    options={"temperature": 0},
)

print("\n=== Appel 2 : reponse finale ===")
print(final.message.content)
