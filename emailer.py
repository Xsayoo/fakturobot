import base64
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

_POSTMARK_API = "https://api.postmarkapp.com"


@dataclass
class InboundEmail:
    from_email: str
    from_name: str
    subject: str
    text_body: str
    html_body: str
    message_id: str


def parse_inbound_payload(payload: dict) -> InboundEmail:
    return InboundEmail(
        from_email=payload.get("FromFull", {}).get("Email", payload.get("From", "")),
        from_name=payload.get("FromFull", {}).get("Name", ""),
        subject=payload.get("Subject", ""),
        text_body=payload.get("TextBody", ""),
        html_body=payload.get("HtmlBody", ""),
        message_id=payload.get("MessageID", ""),
    )


async def _postmark_request(endpoint: str, payload: dict) -> dict:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Postmark-Server-Token": settings.postmark_server_token,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{_POSTMARK_API}{endpoint}", json=payload, headers=headers)
            if resp.status_code >= 400:
                logger.error("Postmark error %s: %s", resp.status_code, resp.text)
                return {}
            return resp.json()
    except Exception as exc:
        logger.error("Postmark request failed: %s", exc)
        return {}


async def send_invoice(
    to_email: str,
    to_name: str,
    from_name: str,
    invoice_number: str,
    recipient_name: str,
    amount_czk: float,
    pdf_bytes: bytes,
    cc_email: Optional[str] = None,
) -> None:
    pdf_b64 = base64.b64encode(pdf_bytes).decode()
    attachments = [
        {
            "Name": f"faktura-{invoice_number}.pdf",
            "Content": pdf_b64,
            "ContentType": "application/pdf",
        }
    ]

    payload: dict = {
        "From": f"{from_name} <{settings.postmark_from_email}>",
        "To": f"{to_name} <{to_email}>",
        "Subject": f"Faktura {invoice_number}",
        "TextBody": (
            f"Dobrý den,\n\n"
            f"v příloze zasílám fakturu č. {invoice_number} na částku {amount_czk:,.0f} Kč.\n\n"
            f"Děkuji za spolupráci.\n\n{from_name}"
        ),
        "Attachments": attachments,
    }

    if cc_email:
        payload["Cc"] = cc_email

    await _postmark_request("/email", payload)


async def send_invoice_copy(
    user_email: str,
    invoice_number: str,
    recipient_name: str,
    amount_czk: float,
    pdf_bytes: bytes,
) -> None:
    pdf_b64 = base64.b64encode(pdf_bytes).decode()
    payload = {
        "From": f"FakturoBot <{settings.postmark_from_email}>",
        "To": user_email,
        "Subject": f"Faktura {invoice_number} odeslána ✓",
        "TextBody": (
            f"Faktura č. {invoice_number} pro {recipient_name} "
            f"na {amount_czk:,.0f} Kč byla úspěšně odeslána.\n\n"
            f"Kopie faktury v příloze."
        ),
        "Attachments": [
            {
                "Name": f"faktura-{invoice_number}.pdf",
                "Content": pdf_b64,
                "ContentType": "application/pdf",
            }
        ],
    }
    await _postmark_request("/email", payload)


async def send_welcome(user_email: str, setup_url: str) -> None:
    payload = {
        "From": f"FakturoBot <{settings.postmark_from_email}>",
        "To": user_email,
        "Subject": "Vítejte ve FakturoBot — nastavte si kartu",
        "TextBody": (
            f"Vítejte!\n\n"
            f"Vaše první faktura je ZDARMA jako zkušební.\n\n"
            f"Pro příští faktury prosím přidejte platební kartu zde:\n{setup_url}\n\n"
            f"Cena: 29 Kč za fakturu.\n\nTým FakturoBot"
        ),
    }
    await _postmark_request("/email", payload)


async def send_clarification_request(user_email: str, missing_fields: list[str]) -> None:
    fields_cs = {
        "amount": "částku",
        "description": "popis služby/zboží",
        "recipient_name": "jméno příjemce",
        "recipient_email": "email příjemce",
    }
    missing_readable = [fields_cs.get(f, f) for f in missing_fields]
    payload = {
        "From": f"FakturoBot <{settings.postmark_from_email}>",
        "To": user_email,
        "Subject": "Upřesněte fakturační údaje",
        "TextBody": (
            f"Nepodařilo se zpracovat váš email.\n\n"
            f"Chybí: {', '.join(missing_readable)}.\n\n"
            f"Zkuste: 'Fakturuj [firma] [částka] Kč za [popis]'\n\n"
            f"Příklad: Fakturuj Novák s.r.o. 15000 Kč za webový vývoj"
        ),
    }
    await _postmark_request("/email", payload)


async def send_reminder(
    to_email: str,
    invoice_number: str,
    amount_czk: float,
    due_date: str,
    reminder_type: str,
    pdf_bytes: Optional[bytes] = None,
) -> None:
    subjects = {
        "7d": f"Připomínka platby — faktura {invoice_number}",
        "14d": f"Upomínka — faktura {invoice_number} po splatnosti",
        "30d": f"Finální upomínka — faktura {invoice_number}",
    }
    bodies = {
        "7d": (
            f"Dobrý den,\n\nrád bych vás upozornil, že faktura č. {invoice_number} "
            f"na {amount_czk:,.0f} Kč je po splatnosti ({due_date}).\n\n"
            f"Prosím o uhrazení. Faktura v příloze.\n\nDěkuji."
        ),
        "14d": (
            f"Dobrý den,\n\nfaktura č. {invoice_number} na {amount_czk:,.0f} Kč "
            f"je stále neuhrazena (splatnost {due_date}).\n\n"
            f"Žádám o neprodlené uhrazení."
        ),
        "30d": (
            f"Dobrý den,\n\nfaktura č. {invoice_number} na {amount_czk:,.0f} Kč "
            f"je po splatnosti více než 30 dní.\n\n"
            f"Pokud dluh neuhradíte, budu nucen přistoupit k právním krokům."
        ),
    }

    attachments = []
    if pdf_bytes:
        attachments.append(
            {
                "Name": f"faktura-{invoice_number}.pdf",
                "Content": base64.b64encode(pdf_bytes).decode(),
                "ContentType": "application/pdf",
            }
        )

    payload = {
        "From": f"FakturoBot <{settings.postmark_from_email}>",
        "To": to_email,
        "Subject": subjects.get(reminder_type, f"Upomínka — faktura {invoice_number}"),
        "TextBody": bodies.get(reminder_type, ""),
        "Attachments": attachments,
    }
    await _postmark_request("/email", payload)
