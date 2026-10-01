"""Indicateurs commerciaux d'Aya."""
from __future__ import annotations

from storage import analytics as read_analytics


def format_analytics() -> str:
    data = read_analytics()
    return ("📊 Analytics Aya\n"
            f"Prospects : {data['leads']}\n"
            f"Qualifiés : {data['qualified']} ({data['qualification_rate']} %)\n"
            f"Transferts humains : {data['handoffs']}\n"
            f"Messages suivis : {data['messages']}")
