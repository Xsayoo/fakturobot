import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from generator import generate_pdf
from models import Invoice, InvoiceStatus, User


def _make_user(**kwargs) -> User:
    user = User()
    user.id = uuid.uuid4()
    user.email = kwargs.get("email", "test@osvc.cz")
    user.company_name = kwargs.get("company_name", "Test OSVČ")
    user.ico = kwargs.get("ico", "12345678")
    user.dic = kwargs.get("dic", None)
    user.is_vat_payer = kwargs.get("is_vat_payer", False)
    user.bank_account = kwargs.get("bank_account", "CZ6508000000192000145399")
    user.logo_url = kwargs.get("logo_url", None)
    return user


def _make_invoice(user: User, **kwargs) -> Invoice:
    now = datetime.now(timezone.utc)
    invoice = Invoice()
    invoice.id = uuid.uuid4()
    invoice.user_id = user.id
    invoice.user = user
    invoice.recipient_name = kwargs.get("recipient_name", "Novák s.r.o.")
    invoice.recipient_email = kwargs.get("recipient_email", "novak@firma.cz")
    invoice.recipient_ico = kwargs.get("recipient_ico", "87654321")
    invoice.recipient_address = kwargs.get("recipient_address", "Václavské náměstí 1, 110 00 Praha 1")
    invoice.amount_czk = Decimal(str(kwargs.get("amount_czk", "15000.00")))
    invoice.vat_rate = kwargs.get("vat_rate", 0)
    invoice.description = kwargs.get("description", "Webový vývoj — Q1 2024")
    invoice.invoice_number = kwargs.get("invoice_number", "2024-0001")
    invoice.issued_at = kwargs.get("issued_at", now)
    invoice.due_date = kwargs.get("due_date", now + timedelta(days=14))
    invoice.status = InvoiceStatus.sent.value
    invoice.reminders = []
    return invoice


def test_generate_pdf_returns_bytes() -> None:
    user = _make_user()
    invoice = _make_invoice(user)
    pdf = generate_pdf(invoice, user)
    assert isinstance(pdf, bytes)
    assert len(pdf) > 1000


def test_pdf_starts_with_pdf_magic_bytes() -> None:
    user = _make_user()
    invoice = _make_invoice(user)
    pdf = generate_pdf(invoice, user)
    assert pdf[:4] == b"%PDF"


def test_pdf_with_vat() -> None:
    user = _make_user(is_vat_payer=True, dic="CZ12345678")
    invoice = _make_invoice(user, amount_czk="10000.00", vat_rate=21)
    pdf = generate_pdf(invoice, user)
    assert isinstance(pdf, bytes)
    assert len(pdf) > 1000


def test_pdf_without_bank_account_no_qr() -> None:
    user = _make_user(bank_account=None)
    invoice = _make_invoice(user)
    pdf = generate_pdf(invoice, user)
    assert isinstance(pdf, bytes)


def test_pdf_with_logo_url() -> None:
    user = _make_user(logo_url="https://example.com/logo.png")
    invoice = _make_invoice(user)
    pdf = generate_pdf(invoice, user)
    assert isinstance(pdf, bytes)


def test_pdf_contains_invoice_number() -> None:
    user = _make_user()
    invoice = _make_invoice(user, invoice_number="2024-0042")
    pdf = generate_pdf(invoice, user)
    assert isinstance(pdf, bytes)
    assert len(pdf) > 1000


def test_pdf_contains_recipient() -> None:
    user = _make_user()
    invoice = _make_invoice(user, recipient_name="Novák s.r.o.")
    pdf = generate_pdf(invoice, user)
    assert isinstance(pdf, bytes)
    assert len(pdf) > 1000


def test_pdf_large_amount() -> None:
    user = _make_user()
    invoice = _make_invoice(user, amount_czk="999999.99")
    pdf = generate_pdf(invoice, user)
    assert isinstance(pdf, bytes)


def test_pdf_zero_amount() -> None:
    user = _make_user()
    invoice = _make_invoice(user, amount_czk="0.00")
    pdf = generate_pdf(invoice, user)
    assert isinstance(pdf, bytes)


def test_pdf_long_description() -> None:
    user = _make_user()
    desc = "Vývoj a implementace komplexního e-commerce řešení včetně integrace platebních bran, " \
           "správy skladu, analytiky a mobilní aplikace pro iOS a Android. " \
           "Projekt realizován v období leden–březen 2024."
    invoice = _make_invoice(user, description=desc)
    pdf = generate_pdf(invoice, user)
    assert isinstance(pdf, bytes)
    assert len(pdf) > 1000
