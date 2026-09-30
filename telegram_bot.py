"""Adaptateur Telegram pour Aya, compatible avec un worker Railway.

Variables Railway requises : TELEGRAM_TOKEN (ou telegram_token) et AYA_ADMIN_ID
(ou admin_id). Aucun token n'est stocké dans le dépôt.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from actions import (
    admin_update,
    conversation_step,
    decode_qr,
    extract_pdf,
    new_conversation_state,
)
from knowledge_store import context_for, load_knowledge
from rag_bot import answer

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters


logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
LOGGER = logging.getLogger("aya.telegram")
# Les URLs Telegram contiennent le token du bot : ne jamais les écrire dans Railway.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
HISTORY: dict[int, list[dict[str, str]]] = {}
PENDING_ADMIN_REPLIES: dict[int, dict[str, str | int]] = {}
CONVERSATION_STATES: dict[int, dict[str, object]] = {}


def env_first(*names: str) -> str:
    """Lit le premier nom d'environnement défini, sans jamais afficher sa valeur."""
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def admin_id_for(update: Update) -> str | None:
    configured = env_first("AYA_ADMIN_ID", "admin_id")
    telegram_user = update.effective_user
    if configured and telegram_user and str(telegram_user.id) == configured:
        return configured
    return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(
            "Bonjour, je suis Aya de Komara Agency. Quel est ton objectif commercial aujourd'hui?"
        )


def catalog_text() -> str:
    """Construit le Catalogue V2 depuis knowledge.json, sans prix inventé."""
    knowledge = load_knowledge()
    catalogue = knowledge["catalogue_v2"]
    lines = ["🚀 " + catalogue["headline"], catalogue["subheadline"], ""]
    lines.extend("⚡ " + point for point in catalogue["proof_points"])
    lines.append("")
    for index, offer in enumerate(catalogue["offers"].values(), start=1):
        popular = " [POPULAIRE]" if offer.get("populaire") else ""
        lines.append(f"{index}. {offer['nom']} — {offer['prix']}{popular}")
        lines.extend(f"   ✓ {feature}" for feature in offer["features"])
        lines.append("")
    lines.extend([
        f"👉 {catalogue['call_to_action']}",
        " • ".join(catalogue["terms"]),
        catalogue["contact"],
    ])
    return "\n".join(lines)


def is_catalogue_request(message: str) -> bool:
    """Reconnaît les formulations courtes qui demandent le catalogue."""
    normalized = " ".join(message.lower().strip().split())
    return normalized in {
        "catalogue", "catalog", "prix", "tarifs", "offres", "montre", "je veux voir"
    }


def action_buttons(buttons: list[str]) -> InlineKeyboardMarkup | None:
    """Transforme les choix commerciaux en boutons Telegram."""
    if not buttons:
        return None
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=f"aya:{label}")]
        for label in buttons
    ])


async def conversation_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Traite les boutons catalogue, objections et closing."""
    query = update.callback_query
    if not query or not query.message:
        return
    await query.answer()
    chat_id = query.message.chat_id
    label = (query.data or "").removeprefix("aya:")
    if label == "catalogue":
        state = CONVERSATION_STATES.setdefault(chat_id, new_conversation_state())
        state["stage"] = "objections"
        await query.message.reply_text(catalog_text(), reply_markup=action_buttons(["WhatsApp Bot", "Telegram Bot", "Instagram Bot", "J'ai une objection"]))
        return
    state = CONVERSATION_STATES.setdefault(chat_id, new_conversation_state())
    result = conversation_step(label, state)
    CONVERSATION_STATES[chat_id] = result["state"]
    await query.message.reply_text(result["reply"], reply_markup=action_buttons(result.get("buttons", [])))


async def catalog_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(catalog_text())


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Commandes admin : instruction, faq, price et apprentissage question||réponse."""
    if not update.message:
        return
    admin_id = admin_id_for(update)
    if not admin_id:
        await update.message.reply_text("Action admin refusée : identifiant non autorisé.")
        return
    text = update.message.text or ""
    command, _, raw = text.partition(" ")
    try:
        if command == "/admin" and raw.startswith("instruction "):
            result = admin_update(admin_id, "instruction", {"text": raw[len("instruction "):].strip()})
        elif command in {"/apprend", "/admin"} and "||" in raw:
            question, answer_text = (part.strip() for part in raw.split("||", 1))
            result = admin_update(admin_id, "faq", {"question": question, "answer": answer_text})
        elif command == "/admin" and raw.startswith("faq ") and "||" in raw[4:]:
            question, answer_text = (part.strip() for part in raw[4:].split("||", 1))
            result = admin_update(admin_id, "faq", {"question": question, "answer": answer_text})
        elif command == "/admin" and raw.startswith("price "):
            offer_id, price = raw[len("price "):].split(maxsplit=1)
            result = admin_update(admin_id, "offer_price", {"offer_id": offer_id, "price_eur": float(price)})
        else:
            await update.message.reply_text(
                "Commandes :\n/admin instruction <texte>\n/apprend <question> || <réponse>\n"
                "/admin price <offer_id> <prix>\n/catalog"
            )
            return
        await update.message.reply_text(f"Mise à jour appliquée : {result['update_type']}.")
    except (PermissionError, ValueError, KeyError) as exc:
        await update.message.reply_text(f"Mise à jour refusée : {exc}")


async def deliver_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Si l'admin répond à une question transférée, renvoie sa réponse au client et l'apprend."""
    if not update.message or not update.message.reply_to_message or not admin_id_for(update):
        return False
    pending = PENDING_ADMIN_REPLIES.get(update.message.reply_to_message.message_id)
    if not pending:
        return False
    client_chat_id = int(pending["client_chat_id"])
    response = update.message.text or ""
    await context.bot.send_message(chat_id=client_chat_id, text=response)
    question = str(pending["question"])
    admin_id = admin_id_for(update)
    if admin_id:
        try:
            admin_update(admin_id, "faq", {"question": question, "answer": response})
        except (PermissionError, ValueError, KeyError):
            LOGGER.exception("Could not persist admin answer")
    await update.message.reply_text("Réponse envoyée au client et ajoutée à la mémoire d'Aya.")
    del PENDING_ADMIN_REPLIES[update.message.reply_to_message.message_id]
    return True


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    chat_id = update.effective_chat.id
    history = HISTORY.setdefault(chat_id, [])[-12:]
    admin_id = admin_id_for(update)
    if await deliver_admin_reply(update, context):
        return
    incoming = update.message.text or ""
    if is_catalogue_request(incoming):
        await update.message.reply_text(catalog_text())
        return
    state = CONVERSATION_STATES.setdefault(chat_id, new_conversation_state())
    result = conversation_step(incoming, state)
    CONVERSATION_STATES[chat_id] = result["state"]
    response = result["reply"]
    await update.message.reply_text(response, reply_markup=action_buttons(result.get("buttons", [])))
    # Les sujets explicitement hors périmètre sont transmis à l'admin.
    if result.get("handoff") and env_first("AYA_ADMIN_ID", "admin_id"):
        admin_chat_id = int(env_first("AYA_ADMIN_ID", "admin_id"))
        forwarded = await context.bot.forward_message(chat_id=admin_chat_id, from_chat_id=chat_id, message_id=update.message.message_id)
        PENDING_ADMIN_REPLIES[forwarded.message_id] = {"client_chat_id": chat_id, "question": incoming}
        await context.bot.send_message(chat_id=admin_chat_id, text="Nouveau handoff commercial : réponds au message transféré pour reprendre la conversation.", reply_to_message_id=forwarded.message_id)
    history.extend([
        {"role": "user", "content": incoming},
        {"role": "assistant", "content": response},
    ])
    HISTORY[chat_id] = history[-12:]
    return


async def document_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Télécharge temporairement un PDF envoyé à Aya puis extrait son texte localement."""
    if not update.message or not update.message.document:
        return
    document = update.message.document
    if document.mime_type != "application/pdf" and not (document.file_name or "").lower().endswith(".pdf"):
        await update.message.reply_text("Je peux analyser les fichiers PDF. Envoie-moi un PDF, s'il te plaît.")
        return
    temporary_path: Path | None = None
    try:
        telegram_file = await document.get_file()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temporary:
            temporary_path = Path(temporary.name)
        await telegram_file.download_to_drive(custom_path=str(temporary_path))
        result = extract_pdf(str(temporary_path))
        text = result["text"][:3500] or "Je n'ai pas trouvé de texte exploitable dans ce PDF."
        await update.message.reply_text(f"PDF analysé ({result['pages']} page(s)) :\n\n{text}")
    except Exception as exc:
        LOGGER.exception("PDF analysis failed: %s", exc)
        await update.message.reply_text("Je n'ai pas pu analyser ce PDF. Vérifie qu'il n'est pas protégé ou scanné en image.")
    finally:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)


async def photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Télécharge temporairement une image et tente de décoder son QR code."""
    if not update.message or not update.message.photo:
        return
    temporary_path: Path | None = None
    try:
        telegram_file = await update.message.photo[-1].get_file()
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temporary:
            temporary_path = Path(temporary.name)
        await telegram_file.download_to_drive(custom_path=str(temporary_path))
        result = decode_qr(str(temporary_path))
        await update.message.reply_text(result["data"] if result["decoded"] else "Je n'ai pas détecté de QR code lisible dans cette image.")
    except Exception:
        LOGGER.exception("QR analysis failed")
        await update.message.reply_text("Je n'ai pas pu lire cette image. Envoie une image nette avec le QR code visible.")
    finally:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)


def build_application(token: str) -> Application:
    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("catalog", catalog_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("apprend", admin_command))
    application.add_handler(CallbackQueryHandler(conversation_button, pattern=r"^aya:"))
    application.add_handler(MessageHandler(filters.Document.ALL, document_message))
    application.add_handler(MessageHandler(filters.PHOTO, photo_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    application.add_handler(MessageHandler(filters.COMMAND, text_message))
    return application


def main() -> None:
    token = env_first("TELEGRAM_TOKEN", "telegram_token")
    if not token:
        raise RuntimeError("Variable Railway manquante : TELEGRAM_TOKEN (ou telegram_token)")
    if not env_first("AYA_ADMIN_ID", "admin_id"):
        LOGGER.warning("AYA_ADMIN_ID/admin_id n'est pas configuré : commandes admin désactivées")
    LOGGER.info("Aya Telegram démarre en polling")
    build_application(token).run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
