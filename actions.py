"""Actions commerciales locales, déterministes et open source pour Aya.

Aucune action externe n'est exécutée automatiquement : les rendez-vous et suivis sont
préparés sous forme de brouillons/fichiers à valider par l'équipe.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from understanding import understand


KNOWLEDGE_PATH = Path(__file__).with_name("knowledge.json")


def _load() -> dict[str, Any]:
    with KNOWLEDGE_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def _save(data: dict[str, Any]) -> None:
    temporary = KNOWLEDGE_PATH.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")
    temporary.replace(KNOWLEDGE_PATH)


def qualify_lead(name: str = "", need: str = "", budget: str = "", timeline: str = "") -> dict[str, Any]:
    """Calcule la qualification : 25 points par champ renseigné, seuil à 75."""
    fields = {"name": name, "need": need, "budget": budget, "timeline": timeline}
    score = min(100, sum(bool(value.strip()) for value in fields.values()) * 25)
    return {**{key: value.strip() for key, value in fields.items()},
            "qualification_score": score,
            "missing_fields": [key for key, value in fields.items() if not value.strip()],
            "status": "qualified" if score >= 75 else "incomplete"}


def recommend_offer(need: str, channels: list[str] | None = None) -> dict[str, Any]:
    """Sélectionne l'offre la plus cohérente sans inventer de prix."""
    knowledge = _load()
    text = f"{need} {' '.join(channels or [])}".lower()
    offers = knowledge["offers"]
    if any(word in text for word in ("whatsapp", "wa")):
        offer = next(item for item in offers if item["id"] == "whatsapp")
    elif "telegram" in text:
        offer = next(item for item in offers if item["id"] == "telegram")
    elif "instagram" in text or "messenger" in text:
        offer = next(item for item in offers if item["id"] == "instagram_messenger")
    elif sum(word in text for word in ("plusieurs", "omni", "multi", "centraliser")):
        offer = next(item for item in offers if item["id"] == "omni")
    else:
        offer = next(item for item in offers if item["id"] == "omni")
    return offer


def format_offer(offer_name: str, objective: str, price_eur: int | float | None = None) -> str:
    """Formate une recommandation avec prix connu ou mention explicite du devis."""
    knowledge = _load()
    known_offer = next((item for item in knowledge["offers"] if item["name"] == offer_name), None)
    price = known_offer.get("price_label", "sur devis uniquement") if known_offer else (
        f"à partir de {price_eur:g}€" if price_eur is not None else "sur devis uniquement"
    )
    return (f"Pour ton objectif {objective.strip()}, le plus adapté c'est {offer_name}. "
            f"Le tarif est {price}. Prochaine étape : je te prépare une reco adaptée à ton objectif?")


def calculate_quote(offer_id: str, quantity: int = 1, addons: dict[str, float] | None = None) -> dict[str, Any]:
    """Calcule un devis transparent à partir des prix de knowledge.json.

    Le Pack Omni reste toujours sur devis : aucun montant fictif n'est produit.
    """
    knowledge = _load()
    offer = next((item for item in knowledge["offers"] if item["id"] == offer_id), None)
    if offer is None:
        raise ValueError(f"Offre inconnue: {offer_id}")
    if offer["starting_price_eur"] is None:
        return {"status": "quote_required", "offer": offer["name"], "reason": "Pack Omni sur devis uniquement"}
    quantity = max(1, int(quantity))
    addon_values = {key: max(0, float(value)) for key, value in (addons or {}).items()}
    subtotal = offer["starting_price_eur"] * quantity
    total = subtotal + sum(addon_values.values())
    return {"status": "calculated", "currency": "EUR", "offer": offer["name"],
            "unit_price": offer["starting_price_eur"], "quantity": quantity,
            "addons": addon_values, "subtotal": subtotal, "total": total,
            "billing": offer.get("billing", "one_time"), "price_label": offer.get("price_label", ""),
            "installation": knowledge["business"]["installation"],
            "payment_methods": knowledge["business"]["payment_methods"]}


def extract_pdf(path: str) -> dict[str, Any]:
    """Extrait le texte d'un PDF local avec pypdf, sans service cloud."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("Installez pypdf pour analyser les PDF") from exc
    file_path = Path(path)
    reader = PdfReader(str(file_path))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    return {"file": str(file_path), "pages": len(pages), "text": "\n\n".join(pages),
            "status": "extracted"}


def decode_qr(path: str) -> dict[str, Any]:
    """Décode un QR code depuis une image avec OpenCV, en local."""
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("Installez opencv-python-headless pour lire les QR codes") from exc
    image = cv2.imread(str(Path(path)))
    if image is None:
        raise ValueError(f"Image illisible: {path}")
    value, points, _ = cv2.QRCodeDetector().detectAndDecode(image)
    return {"file": path, "decoded": bool(value), "data": value,
            "status": "decoded" if value else "not_found", "points": points.tolist() if points is not None else None}


def create_appointment(title: str, start_iso: str, duration_minutes: int = 30, attendee: str = "") -> dict[str, Any]:
    """Prépare un rendez-vous local et son fichier iCalendar à importer."""
    start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    end = start + timedelta(minutes=max(1, int(duration_minutes)))
    uid = secrets.token_hex(12)
    output_dir = Path(os.getenv("AYA_DATA_DIR", "."))
    output_dir.mkdir(parents=True, exist_ok=True)
    ics_path = output_dir / f"appointment-{uid}.ics"
    def ics_date(value: datetime) -> str:
        return value.strftime("%Y%m%dT%H%M%S")
    ics = ("BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Komara Agency//Aya//FR\n"
           "BEGIN:VEVENT\nUID:{uid}\nDTSTAMP:{stamp}\nDTSTART:{start}\nDTEND:{end}\n"
           "SUMMARY:{title}\nATTENDEE:{attendee}\nEND:VEVENT\nEND:VCALENDAR\n").format(
               uid=uid, stamp=ics_date(datetime.now()), start=ics_date(start), end=ics_date(end),
               title=title.replace("\n", " "), attendee=attendee.replace("\n", " "))
    ics_path.write_text(ics, encoding="utf-8")
    return {"status": "draft", "title": title, "start": start.isoformat(), "end": end.isoformat(),
            "attendee": attendee, "ics_path": str(ics_path), "confirmation_required": True}


def create_follow_up(summary: str, next_step: str = "Échange de découverte") -> dict[str, str]:
    return {"summary": summary.strip(), "next_step": next_step.strip(), "status": "draft"}


def handoff_to_human(reason: str) -> dict[str, str]:
    return {"status": "handoff_requested", "reason": reason.strip()}


# ---------------------------------------------------------------------------
# Parcours conversationnel commercial d'Aya
# ---------------------------------------------------------------------------

CONVERSATION_STAGES = (
    "accroche", "qualification", "douleur_solution", "catalogue",
    "objections", "closing", "handoff_suivi",
)


def new_conversation_state() -> dict[str, Any]:
    """Crée un état isolé par prospect, sérialisable si un stockage est ajouté."""
    return {
        "stage": "accroche",
        "name": "",
        "need": "",
        "budget": "",
        "timeline": "",
        "pain": "",
        "offer_id": "",
        "last_question": "",
        "objection": "",
    }


def _short_positive(message: str) -> bool:
    return message.lower().strip() in {"oui", "ok", "d'accord", "yes", "vas-y", "montre", "je veux voir"}


def _short_negative(message: str) -> bool:
    text = message.lower().strip()
    return text in {"non", "bof", "no", "pas intéressé", "laisse", "non laisse"} or "pas intéressé" in text


def _objection_reply(message: str) -> str:
    text = message.lower()
    if any(word in text for word in ("cher", "prix", "budget", "coûte")):
        return "Je comprends. On peut commencer par une seule plateforme et garder un budget maîtrisé. Tu veux partir sur Telegram, WhatsApp ou Instagram?"
    if any(word in text for word in ("réfléchir", "plus tard", "temps")):
        return "Bien sûr, aucun souci. Je peux te laisser une recommandation claire à relire : quel est le principal point qui te fait hésiter?"
    if any(word in text for word in ("confiance", "sécurité", "garantie")):
        return "C'est normal de vérifier. On définit d'abord le périmètre et le résultat attendu avant de lancer quoi que ce soit. Qu'aimerais-tu valider en priorité?"
    return "Je comprends ton hésitation. Qu'est-ce qui te bloque le plus : le budget, le fonctionnement ou le délai?"


def conversation_step(message: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fait avancer un prospect dans les 7 étapes métier.

    Retourne ``stage``, ``reply``, ``buttons`` et ``state``. Cette fonction est
    indépendante de Telegram et peut être utilisée par WhatsApp, une API ou des tests.
    """
    state = {**new_conversation_state(), **(state or {})}
    frame = understand(message, state=state)
    text = frame.normalized
    lower = frame.normalized
    frame_data = {"understanding": frame.to_dict()}
    if not text:
        return {"stage": state["stage"], "reply": "Que souhaites-tu automatiser aujourd'hui?", "buttons": [], "state": state, **frame_data}
    if "human_handoff_required" in frame.policy_flags:
        state["stage"] = "handoff_suivi"
        return {"stage": state["stage"], "reply": "Pour ce sujet, je préfère te passer mon responsable humain pour bien t'accompagner. Il te répond en moins de 2h.", "buttons": [], "state": state, "handoff": True, **frame_data}
    if _short_negative(text):
        state["stage"] = "handoff_suivi"
        return {"stage": state["stage"], "reply": "Compris, je ne t'embête pas. Je te laisse juste un exemple ici au cas où, ça pourra t'aider plus tard.", "buttons": ["catalogue"], "state": state, **frame_data}

    stage = state.get("stage", "accroche")
    if stage == "accroche":
        state["stage"] = "qualification"
        state["last_question"] = "name"
        return {"stage": state["stage"], "reply": "Bonjour, je suis Aya de Komara Agency. Tu fais quoi comme activité aujourd'hui?", "buttons": [], "state": state}

    if stage == "qualification":
        field = state.get("last_question", "name")
        state[field] = text
        if frame.entities.get("budget"):
            state["budget"] = frame.entities["budget"]
        if frame.entities.get("timeline"):
            state["timeline"] = frame.entities["timeline"]
        if frame.entities.get("channel") and not state.get("need"):
            state["need"] = f"automatisation {frame.entities['channel']}"
        lead = qualify_lead(state["name"], state["need"], state["budget"], state["timeline"])
        next_field = lead["missing_fields"][0] if lead["missing_fields"] else None
        questions = {
            "need": "C'est quoi ton objectif principal : avoir plus de clients ou gagner du temps?",
            "budget": "Quel budget approximatif tu avais prévu pour automatiser ça?",
            "timeline": "Tu voudrais que ce soit en place pour quand?",
        }
        if next_field:
            state["last_question"] = next_field
            return {"stage": state["stage"], "reply": questions[next_field], "buttons": [], "state": state, "lead": lead, **frame_data}
        state["stage"] = "douleur_solution"
        state["last_question"] = "pain"
        return {"stage": state["stage"], "reply": "Qu'est-ce qui te prend le plus de temps aujourd'hui dans ta gestion clients?", "buttons": [], "state": state, "lead": lead, **frame_data}

    if stage == "douleur_solution":
        state["pain"] = text
        state["need"] = state["need"] or text
        offer = recommend_offer(state["need"])
        state["offer_id"] = offer["id"]
        state["stage"] = "catalogue"
        return {"stage": state["stage"], "reply": f"Je vois. Pour réduire ce point de friction, le plus adapté serait {offer['name']}. Je te montre les options?", "buttons": ["catalogue", "voir recommandation"], "state": state, "offer": offer}

    if stage == "catalogue":
        if _short_positive(text) or "catalog" in lower or "offre" in lower:
            state["stage"] = "objections"
            return {"stage": state["stage"], "reply": "Voici les offres. Laquelle t'intéresse ou quelle réserve veux-tu qu'on regarde ensemble?", "buttons": ["Telegram Bot", "WhatsApp Bot", "Instagram Bot", "J'ai une objection"], "state": state}
        state["stage"] = "objections"
        state["objection"] = text
        return {"stage": state["stage"], "reply": _objection_reply(text), "buttons": ["WhatsApp Bot", "Telegram Bot", "Parler à un humain"], "state": state}

    if stage == "objections":
        if "humain" in lower or "responsable" in lower:
            state["stage"] = "handoff_suivi"
            return {"stage": state["stage"], "reply": "Je te passe mon responsable humain pour finaliser proprement. Tu préfères être recontacté ici?", "buttons": [], "state": state, "handoff": True}
        if _short_negative(text) or "objection" in lower:
            return {"stage": stage, "reply": _objection_reply(text), "buttons": ["Voir les options", "Parler à un humain"], "state": state}
        state["stage"] = "closing"
        return {"stage": state["stage"], "reply": "Parfait. Tu veux que je prépare le démarrage avec cette option?", "buttons": ["Oui, démarrer", "J'ai une question", "Parler à un humain"], "state": state}

    if stage == "closing":
        if _short_negative(text) or "question" in lower:
            state["stage"] = "objections"
            return {"stage": state["stage"], "reply": _objection_reply(text), "buttons": ["Oui, démarrer", "Parler à un humain"], "state": state}
        if _short_positive(text) or "démarrer" in lower or "commencer" in lower:
            state["stage"] = "handoff_suivi"
            return {"stage": state["stage"], "reply": "Super. Je prépare le suivi avec ton activité, ton besoin et ton délai. Tu confirmes qu'on avance ici?", "buttons": ["Confirmer", "Parler à un humain"], "state": state, "follow_up": True}
        return {"stage": stage, "reply": "Tu veux que je prépare le démarrage ou tu as une dernière question?", "buttons": ["Oui, démarrer", "J'ai une question"], "state": state}

    return {"stage": "handoff_suivi", "reply": "Je peux organiser le suivi avec l'équipe. Tu préfères continuer ici ou parler à un humain?", "buttons": ["Continuer ici", "Parler à un humain"], "state": state}


def admin_update(admin_id: str, update_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Applique une modification à knowledge.json uniquement si l'ID admin correspond.

    L'ID attendu est fourni par la variable d'environnement AYA_ADMIN_ID ; il n'est
    jamais codé en dur ni affiché dans les logs.
    """
    expected = os.getenv("AYA_ADMIN_ID", "").strip()
    if not expected or not secrets.compare_digest(admin_id.strip(), expected):
        raise PermissionError("ID administrateur invalide ou AYA_ADMIN_ID non configuré")
    knowledge = _load()
    if update_type == "instruction":
        instruction = str(payload.get("text", "")).strip()
        if not instruction:
            raise ValueError("text est obligatoire")
        knowledge.setdefault("admin_instructions", []).append(instruction)
    elif update_type == "offer_price":
        offer = next(item for item in knowledge["offers"] if item["id"] == payload["offer_id"])
        price = float(payload["price_eur"])
        if price < 0:
            raise ValueError("Le prix doit être positif")
        offer["starting_price_eur"] = price
        offer["price_label"] = f"à partir de {price:g}€"
    elif update_type == "business_info":
        knowledge["business"].update({key: str(value) for key, value in payload.items()})
    elif update_type == "faq":
        knowledge.setdefault("faq", []).append({"question": str(payload["question"]), "answer": str(payload["answer"])})
    else:
        raise ValueError("Type autorisé: instruction, offer_price, business_info, faq")
    _save(knowledge)
    return {"status": "updated", "update_type": update_type}
