import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parser import InvoiceData, ParseError, parse_email


def _make_mock_response(json_data: dict) -> MagicMock:
    content = MagicMock()
    content.text = json.dumps(json_data)
    message = MagicMock()
    message.content = [content]
    return message


EMAIL_CASES = [
    (
        "Fakturuj Novák s.r.o. 15000 Kč za webový vývoj",
        {"recipient_name": "Novák s.r.o.", "recipient_email": None, "recipient_ico": None,
         "amount": 15000, "currency": "CZK", "description": "webový vývoj",
         "due_days": 14, "vat_rate": 0},
    ),
    (
        "Pošli fakturu na info@firma.cz za konzultace 5000 Kč splatnost 30 dní",
        {"recipient_name": None, "recipient_email": "info@firma.cz", "recipient_ico": None,
         "amount": 5000, "currency": "CZK", "description": "konzultace",
         "due_days": 30, "vat_rate": 0},
    ),
    (
        "Fakturuj IČO 12345678 za grafický design 8500 Kč DPH 21%",
        {"recipient_name": None, "recipient_email": None, "recipient_ico": "12345678",
         "amount": 8500, "currency": "CZK", "description": "grafický design",
         "due_days": 14, "vat_rate": 21},
    ),
    (
        "ABC s.r.o. faktura za správu sítě 12000",
        {"recipient_name": "ABC s.r.o.", "recipient_email": None, "recipient_ico": None,
         "amount": 12000, "currency": "CZK", "description": "správa sítě",
         "due_days": 14, "vat_rate": 0},
    ),
    (
        "Vystav fakturu pro Jana Nováka, jan@novak.cz, 3500 Kč, fotografování akce",
        {"recipient_name": "Jan Novák", "recipient_email": "jan@novak.cz", "recipient_ico": None,
         "amount": 3500, "currency": "CZK", "description": "fotografování akce",
         "due_days": 14, "vat_rate": 0},
    ),
    (
        "Fakturace za překlad dokumentů, 7200 Kč, zákazník: Translations CZ s.r.o.",
        {"recipient_name": "Translations CZ s.r.o.", "recipient_email": None, "recipient_ico": None,
         "amount": 7200, "currency": "CZK", "description": "překlad dokumentů",
         "due_days": 14, "vat_rate": 0},
    ),
    (
        "SEO optimalizace webu pro klienta, 9900 Kč s DPH 10%, splatnost 7 dní",
        {"recipient_name": None, "recipient_email": None, "recipient_ico": None,
         "amount": 9900, "currency": "CZK", "description": "SEO optimalizace webu",
         "due_days": 7, "vat_rate": 10},
    ),
    (
        "Uhradit za účetní poradenství, klient: Novotný s.r.o., částka 4500 CZK",
        {"recipient_name": "Novotný s.r.o.", "recipient_email": None, "recipient_ico": None,
         "amount": 4500, "currency": "CZK", "description": "účetní poradenství",
         "due_days": 14, "vat_rate": 0},
    ),
    (
        "Faktura na 25000 Kč pro XYZ Technologies za vývoj mobilní aplikace, DPH 21%",
        {"recipient_name": "XYZ Technologies", "recipient_email": None, "recipient_ico": None,
         "amount": 25000, "currency": "CZK", "description": "vývoj mobilní aplikace",
         "due_days": 14, "vat_rate": 21},
    ),
    (
        "Vystavit fakturu, příjemce: test@test.com, 1000 Kč za testování",
        {"recipient_name": None, "recipient_email": "test@test.com", "recipient_ico": None,
         "amount": 1000, "currency": "CZK", "description": "testování",
         "due_days": 14, "vat_rate": 0},
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("email_text,expected_json", EMAIL_CASES)
async def test_parse_email_variants(email_text: str, expected_json: dict) -> None:
    mock_response = _make_mock_response(expected_json)

    with patch("parser.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(return_value=mock_response)

        result = await parse_email(email_text, api_key="test-key")

    assert isinstance(result, InvoiceData)
    assert result.amount == expected_json["amount"]
    assert result.description == expected_json["description"]
    assert result.due_days == expected_json["due_days"]
    assert result.vat_rate == expected_json["vat_rate"]


@pytest.mark.asyncio
async def test_parse_email_missing_fields() -> None:
    mock_response = _make_mock_response({"error": "missing_field", "missing": ["amount"]})

    with patch("parser.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(return_value=mock_response)

        result = await parse_email("Pošli fakturu", api_key="test-key")

    assert isinstance(result, ParseError)
    assert "amount" in result.missing


@pytest.mark.asyncio
async def test_parse_email_invalid_json() -> None:
    content = MagicMock()
    content.text = "Toto není JSON"
    message = MagicMock()
    message.content = [content]

    with patch("parser.anthropic.AsyncAnthropic") as MockClient:
        instance = MockClient.return_value
        instance.messages.create = AsyncMock(return_value=message)

        result = await parse_email("Jakýkoliv text", api_key="test-key")

    assert isinstance(result, ParseError)


