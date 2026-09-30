"""Adaptateur Telegram pour Aya, compatible avec un worker Railway.

Variables Railway requises : TELEGRAM_TOKEN (ou telegram_token) et AYA_ADMIN_ID
(ou admin_id). Aucun token n'est stocké dans le dépôt.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from actions import decode_qr, extract_pdf
from rag_bot import answer

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters


logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
LOGGER = logging.getLogger("aya.telegram")
HISTORY: dict[int, list[dict[str, str]]] = {}


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


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    chat_id = update.effective_chat.id
    history = HISTORY.setdefault(chat_id, [])[-12:]
    admin_id = admin_id_for(update)
    response = answer(update.message.text or "", history, admin_id=admin_id)
    await update.message.reply_text(response)
    history.extend([
        {"role": "user", "content": update.message.text or ""},
        {"role": "assistant", "content": response},
    ])
    HISTORY[chat_id] = history[-12:]


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
