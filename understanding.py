"""Pipeline de compréhension d'Aya, inspiré du trajet en six étapes.

Ce module ne prétend pas entraîner un grand modèle dans le bot. Il rend explicites
les couches réellement exécutées à chaque message : données, tokens, nombres,
attention contextuelle, mémoire de connaissances et règles post-entraînement.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any

from knowledge_store import context_for, load_knowledge


@dataclass(frozen=True)
class UnderstandingFrame:
    raw: str
    normalized: str
    tokens: list[str]
    numeric_features: dict[str, float]
    attention_context: list[str]
    knowledge_context: str
    intent: str
    entities: dict[str, str]
    policy_flags: list[str]
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKC", text or "").strip().lower()
    value = re.sub(r"\s+", " ", value)
    return value


def _tokens(text: str) -> list[str]:
    return [token for token in re.findall(r"[\wÀ-ÿ]+", text) if len(token) > 1]


def _numeric_features(tokens: list[str], normalized: str) -> dict[str, float]:
    vocabulary = ("prix", "tarif", "budget", "whatsapp", "telegram", "instagram", "support", "vente", "rendez", "humain", "urgent")
    return {
        "token_count": float(len(tokens)),
        "message_length": float(len(normalized)),
        "question": float("?" in normalized),
        "contains_number": float(bool(re.search(r"\d", normalized))),
        **{f"keyword_{word}": float(word in normalized) for word in vocabulary},
        "semantic_hash": float(int(hashlib.sha256(normalized.encode()).hexdigest()[:8], 16) % 10000) / 10000,
    }


def _attention_context(normalized: str, history: list[dict[str, str]] | None) -> list[str]:
    """Sélection contextuelle légère : récence + recouvrement lexical, sans inventer."""
    query = set(_tokens(normalized))
    candidates = [item.get("content", "") for item in (history or []) if item.get("content")]
    scored: list[tuple[float, str]] = []
    for index, candidate in enumerate(candidates):
        overlap = len(query & set(_tokens(_normalize(candidate))))
        recency = (index + 1) / max(1, len(candidates))
        scored.append((overlap * 2 + recency, candidate))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [text for _, text in scored[-6:]][::-1]


def _entities(normalized: str) -> dict[str, str]:
    entities: dict[str, str] = {}
    for channel in ("whatsapp", "telegram", "instagram", "messenger"):
        if channel in normalized:
            entities["channel"] = channel
            break
    budget = re.search(r"\b(\d+(?:[.,]\d+)?)\s*(?:€|euros?|eur)\b", normalized)
    if budget:
        entities["budget"] = budget.group(0)
    if any(word in normalized for word in ("demain", "urgent", "cette semaine", "ce mois", "24h", "48h")):
        entities["timeline"] = normalized
    return entities


def _intent(normalized: str) -> str:
    if normalized.startswith("/"):
        return "command"
    if any(word in normalized for word in ("prix", "tarif", "coûte", "combien", "budget")):
        return "pricing"
    if any(word in normalized for word in ("rendez-vous", "rdv", "appel", "calendrier")):
        return "appointment"
    if any(word in normalized for word in ("humain", "responsable", "équipe")):
        return "human_handoff"
    if any(word in normalized for word in ("oui", "ok", "d'accord", "vas-y", "démarrer")):
        return "positive"
    if any(word in normalized for word in ("non", "pas intéressé", "laisse tomber")):
        return "negative"
    if any(word in normalized for word in ("catalogue", "offre", "solution", "bot")):
        return "offer_discovery"
    return "discovery"


def understand(message: str, history: list[dict[str, str]] | None = None, state: dict[str, Any] | None = None) -> UnderstandingFrame:
    """Exécute les six couches et retourne une représentation vérifiable."""
    normalized = _normalize(message)
    tokens = _tokens(normalized)
    knowledge = load_knowledge()
    flags: list[str] = []
    if any(topic in normalized for topic in knowledge["scope"]["handoff_topics"]):
        flags.append("human_handoff_required")
    if normalized in knowledge["conversation_rules"]["short_negative"]:
        flags.append("stop_sales")
    if not normalized:
        flags.append("empty_input")
    confidence = min(0.99, 0.35 + min(len(tokens), 12) * 0.04 + (0.15 if state else 0))
    return UnderstandingFrame(
        raw=message,
        normalized=normalized,
        tokens=tokens,
        numeric_features=_numeric_features(tokens, normalized),
        attention_context=_attention_context(normalized, history),
        knowledge_context=context_for(normalized) if normalized else "Aucun contexte spécifique.",
        intent=_intent(normalized),
        entities=_entities(normalized),
        policy_flags=flags,
        confidence=round(confidence, 2),
    )
