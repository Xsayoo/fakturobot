import json
import logging
from dataclasses import dataclass
from typing import Optional, Union

import anthropic

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Jsi pomocník pro zpracování fakturačních emailů.
Extrahuj z emailu strukturovaná data.

KRITICKY DŮLEŽITÉ: Odpověz VÝHRADNĚ surovým JSON objektem. Žádný markdown, žádné backticky, žádné ```json, žádný text před ani za JSON. Pouze { ... }.

JSON schema:
{
  "recipient_name": "string nebo null",
  "recipient_email": "string nebo null",
  "recipient_ico": "string nebo null",
  "amount": number (číslo bez DPH, např. 15000),
  "currency": "CZK",
  "description": "string (popis služby)",
  "due_days": number (default 14),
  "vat_rate": 0 nebo 21 nebo 15 nebo 10 (default 0)
}

Příklad správné odpovědi:
{"recipient_name": "Novák s.r.o.", "recipient_email": null, "recipient_ico": null, "amount": 15000, "currency": "CZK", "description": "webový vývoj", "due_days": 14, "vat_rate": 0}

Pokud nelze určit amount nebo description, vrať pouze: {"error": "missing_field", "missing": ["amount"]}
"""


@dataclass
class InvoiceData:
    recipient_name: Optional[str]
    recipient_email: Optional[str]
    recipient_ico: Optional[str]
    amount: float
    currency: str
    description: str
    due_days: int
    vat_rate: int


@dataclass
class ParseError:
    missing: list[str]


async def parse_email(email_text: str, api_key: str) -> Union[InvoiceData, ParseError]:
    client = anthropic.AsyncAnthropic(api_key=api_key)

    try:
        logger.error("DEBUG: calling Claude model with email: %s", email_text[:100])
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": email_text}],
        )

        logger.error("DEBUG: Claude response content blocks: %s", [(b.type, getattr(b, 'text', '')[:50]) for b in message.content])

        raw = next(
            (block.text for block in message.content if block.type == "text"),
            ""
        ).strip()
        logger.error("DEBUG: raw text: %r", raw[:200])

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
            logger.error("DEBUG: after strip: %r", raw[:200])

        data = json.loads(raw)

        if "error" in data:
            return ParseError(missing=data.get("missing", []))

        return InvoiceData(
            recipient_name=data.get("recipient_name"),
            recipient_email=data.get("recipient_email"),
            recipient_ico=data.get("recipient_ico"),
            amount=float(data["amount"]),
            currency=data.get("currency", "CZK"),
            description=str(data["description"]),
            due_days=int(data.get("due_days", 14)),
            vat_rate=int(data.get("vat_rate", 0)),
        )

    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.error("Failed to parse Claude response: %s | raw was: %r", exc, locals().get('raw', 'N/A'))
        return ParseError(missing=["amount", "description"])
    except anthropic.APIError as exc:
        logger.error("Anthropic API error: %s", exc)
        return ParseError(missing=["amount", "description"])
    except Exception as exc:
        logger.error("Unexpected parser error: %s", exc, exc_info=True)
        return ParseError(missing=["amount", "description"])
