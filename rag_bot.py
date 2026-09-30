"""Aya, agente commerciale RAG de Komara Agency.

Lancement local : python rag_bot.py
Avec OpenAI : définir OPENAI_API_KEY et éventuellement OPENAI_MODEL.
Sans clé API, Aya utilise un mode de secours utile pour tester la mémoire et les actions.
"""

from __future__ import annotations

import os
from typing import Any

from knowledge_store import context_for, load_knowledge

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - permet le mode de secours sans dépendance
    OpenAI = None  # type: ignore[assignment]


SYSTEM_PROMPT = """Tu es Aya, l'agente commerciale de Komara Agency.
Tu réponds en français, avec chaleur, précision et concision.
Tu qualifies le besoin avant de recommander une offre. Tu ne fabriques jamais de prix,
délais, garanties ou informations absentes de la mémoire. Termine si possible par une
prochaine étape claire. Si le sujet est complexe ou hors périmètre, propose un transfert
à un humain.

Mémoire pertinente pour ce tour :
{context}
"""


def fallback_reply(message: str, knowledge: dict[str, Any]) -> str:
    """Réponse locale de démonstration quand aucune clé LLM n'est configurée."""
    context = context_for(message)
    if context == "Aucun passage spécifique trouvé.":
        return "Je peux vous aider à clarifier votre objectif, votre cible et votre prochaine étape. Pouvez-vous m'en dire un peu plus sur votre besoin ?"
    return (
        "Voici ce que j'ai trouvé dans ma mémoire :\n"
        f"{context}\n\n"
        "Pour vous orienter correctement, quel est votre objectif principal et dans quel délai souhaitez-vous avancer ?"
    )


def answer(message: str, history: list[dict[str, str]] | None = None) -> str:
    """Répond à un message en utilisant la mémoire locale puis le modèle configuré."""
    knowledge = load_knowledge()
    context = context_for(message)
    if not os.getenv("OPENAI_API_KEY") or OpenAI is None:
        return fallback_reply(message, knowledge)

    client = OpenAI()
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT.format(context=context)},
    ]
    messages.extend(history or [])
    messages.append({"role": "user", "content": message})
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=messages,
        temperature=0.4,
    )
    return response.choices[0].message.content or "Je n'ai pas pu générer une réponse."


def main() -> None:
    print("Aya — Komara Agency. Tapez 'quit' pour quitter.")
    history: list[dict[str, str]] = []
    while True:
        try:
            message = input("Vous : ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if message.lower() in {"quit", "exit", "q"}:
            break
        if not message:
            continue
        reply = answer(message, history)
        print(f"Aya : {reply}\n")
        history.extend([
            {"role": "user", "content": message},
            {"role": "assistant", "content": reply},
        ])


if __name__ == "__main__":
    main()
