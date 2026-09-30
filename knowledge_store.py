"""Mémoire locale de l'agent Aya : chargement et recherche dans knowledge.json."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


KNOWLEDGE_PATH = Path(__file__).with_name("knowledge.json")


def load_knowledge(path: Path = KNOWLEDGE_PATH) -> dict[str, Any]:
    """Charge la base de connaissances JSON."""
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[\wÀ-ÿ]+", text.lower())
        if len(token) > 2
    }


def _flatten(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        chunks: list[str] = []
        for key, item in value.items():
            chunks.extend(_flatten(item, f"{prefix}{key}: "))
        return chunks
    if isinstance(value, list):
        return [chunk for item in value for chunk in _flatten(item, prefix)]
    return [f"{prefix}{value}"]


def search_knowledge(query: str, knowledge: dict[str, Any] | None = None, limit: int = 5) -> list[str]:
    """Retourne les passages les plus proches par recouvrement lexical."""
    knowledge = knowledge or load_knowledge()
    query_tokens = _tokens(query)
    passages = _flatten(knowledge)
    scored = []
    for passage in passages:
        score = len(query_tokens & _tokens(passage))
        if score:
            scored.append((score, passage))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [passage for _, passage in scored[:limit]]


def context_for(query: str, limit: int = 6) -> str:
    """Construit le contexte à injecter dans le prompt de l'agent."""
    passages = search_knowledge(query, limit=limit)
    return "\n".join(f"- {passage}" for passage in passages) or "Aucun passage spécifique trouvé."
