import logging

import stripe
from fastapi import HTTPException, Request

from config import settings
from models import Invoice, InvoiceStatus, User

logger = logging.getLogger(__name__)

# stripe.api_key is set globally in app.py


def get_or_create_customer(user: User) -> str:
    if user.stripe_customer_id:
        return user.stripe_customer_id
    customer = stripe.Customer.create(
        email=user.email,
        metadata={"user_id": str(user.id)},
    )
    return customer.id


def create_setup_link(user: User, return_url: str) -> str:
    customer_id = get_or_create_customer(user)
    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="setup",
        currency="czk",
        success_url=return_url + "?setup=success",
        cancel_url=return_url + "?setup=cancelled",
    )
    return session.url


def charge_for_invoice(user: User, invoice: Invoice) -> str:
    payment_methods = stripe.PaymentMethod.list(
        customer=user.stripe_customer_id,
        type="card",
    )

    if not payment_methods.data:
        raise ValueError("No saved payment method")

    pm_id = payment_methods.data[0].id

    intent = stripe.PaymentIntent.create(
        amount=settings.invoice_price_czk * 100,
        currency="czk",
        customer=user.stripe_customer_id,
        payment_method=pm_id,
        confirm=True,
        off_session=True,
        metadata={
            "invoice_id": str(invoice.id),
            "invoice_number": invoice.invoice_number,
        },
    )
    return intent.id


def create_payment_link(user: User, invoice: Invoice, return_url: str) -> str:
    customer_id = get_or_create_customer(user)
    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="payment",
        line_items=[
            {
                "price_data": {
                    "currency": "czk",
                    "unit_amount": settings.invoice_price_czk * 100,
                    "product_data": {
                        "name": f"FakturoBot — faktura {invoice.invoice_number}"
                    },
                },
                "quantity": 1,
            }
        ],
        success_url=return_url + "?payment=success",
        cancel_url=return_url + "?payment=cancelled",
        metadata={
            "invoice_id": str(invoice.id),
            "invoice_number": invoice.invoice_number,
        },
    )
    return session.url


def construct_webhook_event(body: bytes, signature: str) -> dict:
    return stripe.Webhook.construct_event(body, signature, settings.stripe_webhook_secret)
