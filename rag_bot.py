"""Aya, agente commerciale open source de Komara Agency.

Fonctions locales : qualification, devis, analyse PDF, lecture QR, rendez-vous iCalendar
et mises à jour administrateur. Les actions externes restent des brouillons à confirmer.
"""

from __future__ import annotations

import os
import re
import json
from urllib.request import Request, urlopen
from typing import Any

from actions import (
    admin_update,
    calculate_quote,
    create_appointment,
    decode_qr,
    extract_pdf,
    format_offer,
    handoff_to_human,
    qualify_lead,
    recommend_offer,
)
from knowledge_store import context_for, load_knowledge
from understanding import understand

SYSTEM_PROMPT = """Tu es AYA, agente commerciale de Komara Agency. Tu es une femme de 26 ans,
chaleureuse, professionnelle, directe, et tu ne dis jamais que tu es une IA.
Réponds en français par défaut, adapte le tutoiement/vouvoiement, en 2 ou 3 phrases maximum.
Qualifie avant de vendre : nom/activité, besoin, budget approximatif et délai. Chaque champ
vaut 25 points et il faut au moins 75 points avant toute offre finale. Pose une seule question
utile à la fois. Pour une réponse courte positive, demande l'information manquante la plus
logique; pour une réponse négative, arrête la vente sans harceler; pour 'je sais pas', aide
avec une question sur ce qui prend le plus de temps. N'invente jamais un prix, délai ou
fonctionnalité. Pour juridique, médical, litige, comptabilité, site complet ou sujet sensible,
transfère à un humain. Termine par une question ouverte utile.

Mémoire pertinente :
{context}

État de qualification : {lead_state}

Analyse structurée du message : {understanding}
"""


def _contains(message: str, words: list[str]) -> bool:
    normalized = message.lower().strip()
    return any(word in normalized for word in words)


def _missing_question(state: dict[str, Any]) -> str:
    questions = {
        "name": "Top. C'est pour quelle activité? Comment je peux t'appeler?",
        "need": "Parfait. Pour que l'exemple soit vraiment utile, tu fais quoi exactement aujourd'hui?",
        "budget": "Parfait, je te prépare ça. Tu avais quel budget en tête pour automatiser ça?",
        "timeline": "Super. Tu voudrais que ce soit en place pour quand?",
    }
    return questions[state["missing_fields"][0]]


def _state_from_history(history: list[dict[str, str]] | None) -> dict[str, str]:
    text = " ".join(item.get("content", "") for item in (history or []) if item.get("role") == "user")
    state = {"name": "", "need": "", "budget": "", "timeline": ""}
    if any(channel in text.lower() for channel in ("whatsapp", "telegram", "instagram", "messenger")):
        state["need"] = text[-300:]
    if re.search(r"\b\d+\s*(€|euros?|eur)\b", text.lower()):
        state["budget"] = re.search(r"\b\d+\s*(?:€|euros?|eur)\b", text.lower()).group(0)
    if re.search(r"(demain|semaine|mois|24.?48.?h|urgent)", text.lower()):
        state["timeline"] = text[-80:]
    return state


def _deterministic_reply(message: str, history: list[dict[str, str]] | None) -> str | None:
    """Gère les règles critiques avant d'appeler un modèle éventuel."""
    knowledge = load_knowledge()
    frame = understand(message, history)
    lowered = frame.normalized
    if "human_handoff_required" in frame.policy_flags:
        handoff_to_human(reason=message)
        return knowledge["scope"]["handoff_reply"]
    if lowered in knowledge["conversation_rules"]["short_negative"] or _contains(lowered, ["pas intéressé", "laisse tomber"]):
        return knowledge["conversation_rules"]["negative_reply"]
    if lowered in knowledge["conversation_rules"]["unknown_answer"] or _contains(lowered, ["je sais pas", "jsp"]):
        return knowledge["conversation_rules"]["unknown_reply"]

    state = _state_from_history(history)
    current = qualify_lead(**state)
    if current["qualification_score"] < 75:
        # Pour un premier message commercial, commencer par le besoin avant le prix.
        if not history and (_contains(lowered, ["combien", "prix", "tarif"])):
            return "Pour te donner le bon prix sans inventer, c'est pour automatiser quoi exactement : tes ventes ou ton support?"
        if lowered in knowledge["conversation_rules"]["short_positive"] or not history:
            return _missing_question(current)
    else:
        offer = recommend_offer(current["need"])
        quote = calculate_quote(offer["id"])
        price = quote.get("unit_price")
        return format_offer(offer["name"], current["need"], price)
    return None


def answer(message: str, history: list[dict[str, str]] | None = None, admin_id: str | None = None) -> str:
    """Répond à un prospect; les intégrations peuvent passer admin_id séparément."""
    knowledge = load_knowledge()
    if message.startswith("/admin "):
        if not admin_id:
            return "Action admin refusée : identifiant administrateur absent."
        command = message[len("/admin "):].strip()
        kind, _, raw = command.partition(" ")
        try:
            if kind == "instruction":
                result = admin_update(admin_id, "instruction", {"text": raw})
            else:
                return "Commande admin disponible : /admin instruction <nouvelle instruction>"
            return f"Mise à jour appliquée : {result['update_type']}."
        except (PermissionError, ValueError) as exc:
            return f"Mise à jour refusée : {exc}"

    deterministic = _deterministic_reply(message, history)
    if deterministic is not None:
        return deterministic
    frame = understand(message, history)
    context = frame.knowledge_context
    ollama_host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    ollama_model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    try:
        state = qualify_lead(**_state_from_history(history))
        messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT.format(context=context, lead_state=state, understanding=frame.to_dict())}]
        messages.extend(history or [])
        messages.append({"role": "user", "content": message})
        request = Request(f"{ollama_host}/api/chat", data=json.dumps({"model": ollama_model, "messages": messages, "stream": False, "options": {"temperature": 0.35}}).encode(), headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=30) as response:
            content = json.loads(response.read().decode()).get("message", {}).get("content", "").strip()
        if content:
            return content
    except Exception:
        pass
    return "Je peux te préparer une recommandation adaptée. Quel est ton objectif principal et pour quand veux-tu que ce soit en place?"


def main() -> None:
    print("Aya — Komara Agency. Tapez 'quit' pour quitter.")
    print("Fonctions locales: /pdf <chemin>, /qr <chemin>, /devis <offre>, /rdv <ISO> <titre>")
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
        try:
            if message.startswith("/pdf "):
                reply = str(extract_pdf(message[5:].strip()))
            elif message.startswith("/qr "):
                reply = str(decode_qr(message[4:].strip()))
            elif message.startswith("/devis "):
                reply = str(calculate_quote(message[7:].strip()))
            elif message.startswith("/rdv "):
                start, _, title = message[5:].partition(" ")
                reply = str(create_appointment(title or "Échange Komara Agency", start))
            else:
                reply = answer(message, history)
        except (ValueError, RuntimeError, FileNotFoundError) as exc:
            reply = f"Action impossible : {exc}"
        print(f"Aya : {reply}\n")
        history.extend([{"role": "user", "content": message}, {"role": "assistant", "content": reply}])


if __name__ == "__main__":
    main()
