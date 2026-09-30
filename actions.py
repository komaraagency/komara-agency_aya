"""Actions commerciales déterministes d'Aya."""

from __future__ import annotations

from typing import Any


def qualify_lead(name: str = "", need: str = "", budget: str = "", timeline: str = "") -> dict[str, Any]:
    """Produit une fiche de qualification sans envoyer de données à un service externe."""
    answered = sum(bool(value.strip()) for value in (name, need, budget, timeline))
    score = min(100, answered * 25)
    return {
        "name": name.strip(),
        "need": need.strip(),
        "budget": budget.strip(),
        "timeline": timeline.strip(),
        "qualification_score": score,
        "status": "qualified" if score >= 75 else "incomplete"
    }


def create_follow_up(summary: str, next_step: str = "Échange de découverte") -> dict[str, str]:
    """Prépare un suivi à valider avant tout envoi réel."""
    return {
        "summary": summary.strip(),
        "next_step": next_step.strip(),
        "status": "draft"
    }


def format_offer(offer_name: str, objective: str) -> str:
    """Formate une recommandation commerciale sans inventer de prix."""
    return (
        f"Recommandation : {offer_name}.\n"
        f"Objectif identifié : {objective.strip()}.\n"
        "Prochaine étape : valider le périmètre lors d'un échange de découverte."
    )


def handoff_to_human(reason: str) -> dict[str, str]:
    """Prépare un transfert vers un membre de l'équipe."""
    return {"status": "handoff_requested", "reason": reason.strip()}
