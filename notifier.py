import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

_TG_URL = "https://api.telegram.org/bot{token}/sendMessage"


async def send(message: str) -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.warning("Telegram not configured, skipping notification")
        return

    url = _TG_URL.format(token=settings.telegram_bot_token)
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
    except Exception as exc:
        logger.error("Telegram notification failed: %s", exc)


async def invoice_sent(invoice_number: str, recipient: str, amount_czk: float) -> None:
    await send(
        f"✅ Faktura <b>{invoice_number}</b> | {recipient} | "
        f"<b>{amount_czk:,.0f} Kč</b> | odesláno"
    )


async def payment_failed(invoice_number: str, user_email: str, error: str) -> None:
    await send(
        f"❌ Platba selhala | Faktura <b>{invoice_number}</b> | "
        f"Uživatel: {user_email} | Chyba: {error}"
    )


async def pdf_failed(user_email: str, error: str) -> None:
    await send(f"❌ PDF generování selhalo | Uživatel: {user_email} | Chyba: {error}")


async def new_user(email: str) -> None:
    await send(f"👤 Nový uživatel: <b>{email}</b>")
