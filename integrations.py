"""Connecteurs externes optionnels d'Aya.

Aucun secret n'est stocké ici. Chaque fournisseur est activé uniquement si ses
variables d'environnement sont présentes. Les appels de paiement créent des
liens/ordres hébergés par le fournisseur; Aya ne reçoit jamais de données carte.
"""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.request import Request, urlopen


def _service_account_info() -> dict[str, Any] | None:
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON doit contenir un JSON valide") from exc


def append_google_sheet(row: list[Any]) -> dict[str, Any]:
    """Ajoute une ligne via Google Sheets API; retourne disabled si non configuré."""
    spreadsheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
    if not spreadsheet_id:
        return {"status": "disabled", "reason": "GOOGLE_SHEET_ID absent"}
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError("Installez google-api-python-client et google-auth") from exc
    info = _service_account_info()
    if not info:
        return {"status": "disabled", "reason": "GOOGLE_SERVICE_ACCOUNT_JSON absent"}
    credentials = service_account.Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    result = service.spreadsheets().values().append(spreadsheetId=spreadsheet_id, range=os.getenv("GOOGLE_SHEET_RANGE", "Leads!A:J"), valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS", body={"values": [row]}).execute()
    return {"status": "sent", "updated_range": result.get("updates", {}).get("updatedRange", "")}


def create_google_calendar_event(title: str, start_iso: str, duration_minutes: int = 30, attendee: str = "") -> dict[str, Any]:
    calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "").strip()
    if not calendar_id:
        return {"status": "disabled", "reason": "GOOGLE_CALENDAR_ID absent"}
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError("Installez google-api-python-client et google-auth") from exc
    info = _service_account_info()
    if not info:
        return {"status": "disabled", "reason": "GOOGLE_SERVICE_ACCOUNT_JSON absent"}
    start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    end = start + timedelta(minutes=max(1, int(duration_minutes)))
    credentials = service_account.Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/calendar"])
    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    event: dict[str, Any] = {"summary": title, "start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()}}
    if attendee:
        event["attendees"] = [{"email": attendee}]
    created = service.events().insert(calendarId=calendar_id, body=event, sendUpdates="all").execute()
    return {"status": "created", "id": created.get("id"), "html_link": created.get("htmlLink")}


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    request = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", **headers}, method="POST")
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode())


def create_payment_link(provider: str, offer_id: str, amount_eur: float, chat_id: int, description: str) -> dict[str, Any]:
    provider = provider.lower().strip()
    reference = f"aya-{chat_id}-{secrets.token_hex(6)}"
    if provider == "stripe":
        if not os.getenv("STRIPE_SECRET_KEY", "").strip():
            return {"status": "disabled", "reason": "STRIPE_SECRET_KEY absent"}
        try:
            import stripe
        except ImportError as exc:
            raise RuntimeError("Installez stripe") from exc
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
        session = stripe.checkout.Session.create(mode="payment", line_items=[{"price_data": {"currency": "eur", "product_data": {"name": description}, "unit_amount": round(amount_eur * 100)}, "quantity": 1}], metadata={"aya_reference": reference, "chat_id": str(chat_id)}, success_url=os.getenv("STRIPE_SUCCESS_URL", "https://example.com/success"), cancel_url=os.getenv("STRIPE_CANCEL_URL", "https://example.com/cancel"))
        return {"status": "created", "provider": provider, "reference": reference, "url": session.url}
    if provider == "paypal":
        token = os.getenv("PAYPAL_ACCESS_TOKEN", "")
        endpoint = os.getenv("PAYPAL_API_BASE", "https://api-m.sandbox.paypal.com")
        if not token:
            return {"status": "disabled", "reason": "PAYPAL_ACCESS_TOKEN absent"}
        result = _post_json(f"{endpoint}/v2/checkout/orders", {"intent": "CAPTURE", "purchase_units": [{"reference_id": reference, "description": description, "amount": {"currency_code": "EUR", "value": f"{amount_eur:.2f}"}}], "application_context": {"return_url": os.getenv("PAYPAL_RETURN_URL", "https://example.com/success"), "cancel_url": os.getenv("PAYPAL_CANCEL_URL", "https://example.com/cancel")}}, {"Authorization": f"Bearer {token}"})
        approve = next((link["href"] for link in result.get("links", []) if link.get("rel") == "approve"), "")
        return {"status": "created", "provider": provider, "reference": reference, "order_id": result.get("id"), "url": approve}
    if provider in {"orange_money", "om"}:
        endpoint = os.getenv("ORANGE_MONEY_CHECKOUT_URL", "")
        token = os.getenv("ORANGE_MONEY_ACCESS_TOKEN", "")
        if not endpoint or not token:
            return {"status": "disabled", "reason": "ORANGE_MONEY_CHECKOUT_URL/ORANGE_MONEY_ACCESS_TOKEN absents"}
        result = _post_json(endpoint, {"amount": amount_eur, "currency": "EUR", "reference": reference, "description": description, "return_url": os.getenv("ORANGE_MONEY_RETURN_URL", "")}, {"Authorization": f"Bearer {token}"})
        return {"status": "created", "provider": provider, "reference": reference, "url": result.get("checkout_url") or result.get("payment_url"), "raw_status": result.get("status")}
    raise ValueError("Fournisseur de paiement autorisé: stripe, paypal ou orange_money")
