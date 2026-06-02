import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class InvoiceStatus(str, Enum):
    draft = "draft"
    sent = "sent"
    paid = "paid"
    overdue = "overdue"
    cancelled = "cancelled"
    pending_payment = "pending_payment"


class ReminderType(str, Enum):
    day7 = "7d"
    day14 = "14d"
    day30 = "30d"


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    stripe_customer_id = Column(String, nullable=True)
    invoice_email = Column(String, nullable=True)
    company_name = Column(String, nullable=True)
    ico = Column(String, nullable=True)
    dic = Column(String, nullable=True)
    logo_url = Column(String, nullable=True)
    is_vat_payer = Column(Boolean, default=False, nullable=False)
    bank_account = Column(String, nullable=True)
    default_due_days = Column(Integer, default=14, nullable=False)
    setup_token = Column(String, nullable=True, unique=True)

    invoices = relationship("Invoice", back_populates="user", cascade="all, delete-orphan")

    @property
    def has_card(self) -> bool:
        return self.stripe_customer_id is not None


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    recipient_name = Column(String, nullable=True)
    recipient_email = Column(String, nullable=True)
    recipient_ico = Column(String, nullable=True)
    recipient_address = Column(Text, nullable=True)
    amount_czk = Column(Numeric(12, 2), nullable=False)
    vat_rate = Column(Integer, default=0, nullable=False)
    description = Column(Text, nullable=False)
    invoice_number = Column(String, unique=True, nullable=False)
    issued_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    due_date = Column(DateTime(timezone=True), nullable=False)
    status = Column(String, default=InvoiceStatus.draft, nullable=False)
    pdf_path = Column(String, nullable=True)
    pdf_url = Column(String, nullable=True)
    stripe_charge_id = Column(String, nullable=True)
    raw_email_text = Column(Text, nullable=True)

    user = relationship("User", back_populates="invoices")
    reminders = relationship("Reminder", back_populates="invoice", cascade="all, delete-orphan")

    @property
    def amount_vat(self) -> Decimal:
        return self.amount_czk * Decimal(self.vat_rate) / 100

    @property
    def amount_total(self) -> Decimal:
        return self.amount_czk + self.amount_vat


class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False)
    scheduled_for = Column(DateTime(timezone=True), nullable=False)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    reminder_type = Column(String, nullable=False)

    invoice = relationship("Invoice", back_populates="reminders")
