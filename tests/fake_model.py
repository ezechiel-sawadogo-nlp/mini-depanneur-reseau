"""Un faux modèle pour tester les agents sans LLM.

Les agents reçoivent leur fonction d'appel au modèle en paramètre (chat=...).
Dans les tests, on leur passe une fonction écrite à la main qui renvoie des réponses
prévues d'avance. On vérifie ainsi la mécanique (boucle, garde-fous, cloisonnement)
sans attendre le modèle et sans dépendre de ses réponses.
"""

import json
import types

from ollama import Message


def reply(calls: list[tuple[str, dict]] | None = None, content: str = ""):
    """Fabrique une réponse du modèle : du texte, ou des demandes d'outils.

    calls : liste de (nom de l'outil, arguments), par exemple [("get_alarms", {"domain": "ran"})].
    """
    tool_calls = [
        Message.ToolCall(function=Message.ToolCall.Function(name=name, arguments=arguments))
        for name, arguments in (calls or [])
    ] or None
    return types.SimpleNamespace(
        message=Message(role="assistant", content=content, tool_calls=tool_calls),
        prompt_eval_count=100,
        eval_count=10,
    )


def json_reply(data: dict):
    """Une réponse finale au format JSON."""
    return reply(content=json.dumps(data))


class Recorder:
    """Enveloppe un faux modèle et garde la trace de tout ce qu'on lui a envoyé."""

    def __init__(self, answer):
        self.answer = answer  # fonction (**kwargs) -> réponse
        self.requests: list[dict] = []

    def __call__(self, **kwargs):
        self.requests.append(kwargs)
        return self.answer(**kwargs)
