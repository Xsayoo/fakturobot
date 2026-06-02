import logging
import secrets
from datetime import datetime, timedelta, timezone
import stripe
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

import emailer
import notifier
import scheduler
import stripe_handler
from ares import lookup_ico
from config import settings
from database import SessionLocal, create_tables, get_db
from generator import generate_pdf
from models import Invoice, InvoiceStatus, User
from parser import ParseError, parse_email

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="FakturoBot")

stripe.api_key = settings.stripe_secret_key


@app.on_event("startup")
async def startup() -> None:
    create_tables()
    scheduler.start(db_factory=SessionLocal)
    logger.info("FakturoBot started")


@app.on_event("shutdown")
async def shutdown() -> None:
    scheduler.stop()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Postmark inbound webhook
# ---------------------------------------------------------------------------

@app.post("/inbound")
async def inbound(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    payload = await request.json()
    inbound_email = emailer.parse_inbound_payload(payload)
    from_email = inbound_email.from_email.lower().strip()

    email_text = inbound_email.text_body or inbound_email.html_body or inbound_email.subject
    if not email_text.strip():
        return JSONResponse({"status": "ignored", "reason": "empty body"})

    # 1. Find or create user
    user = db.query(User).filter(User.email == from_email).first()
    is_new_user = user is None

    if is_new_user:
        setup_token = secrets.token_urlsafe(32)
        user = User(
            email=from_email,
            setup_token=setup_token,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        await notifier.new_user(from_email)

    # 2. Parse email with Claude
    result = await parse_email(email_text, settings.anthropic_api_key)

    if isinstance(result, ParseError):
        await emailer.send_clarification_request(from_email, result.missing)
        return JSONResponse({"status": "clarification_requested", "missing": result.missing})

    # 3. ARES lookup (best-effort)
    ares_data = None
    if result.recipient_ico:
        ares_data = await lookup_ico(result.recipient_ico)

    # 4. Determine recipient info
    recipient_name = result.recipient_name
    recipient_address = None
    if ares_data:
        recipient_name = recipient_name or ares_data.name
        recipient_address = ares_data.address

    # 5. Generate invoice number
    year = datetime.now(timezone.utc).year
    count = db.query(Invoice).filter(Invoice.user_id == user.id).count() + 1
    invoice_number = f"{year}-{count:04d}"

    # 6. Build invoice record
    issued_at = datetime.now(timezone.utc)
    due_days = result.due_days or user.default_due_days or 14
    due_date = issued_at + timedelta(days=due_days)

    invoice = Invoice(
        user_id=user.id,
        recipient_name=recipient_name,
        recipient_email=result.recipient_email,
        recipient_ico=result.recipient_ico,
        recipient_address=recipient_address,
        amount_czk=result.amount,
        vat_rate=result.vat_rate if user.is_vat_payer else 0,
        description=result.description,
        invoice_number=invoice_number,
        issued_at=issued_at,
        due_date=due_date,
        status=InvoiceStatus.draft.value,
        raw_email_text=email_text[:4000],
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)

    # 7. Generate PDF
    try:
        pdf_bytes = generate_pdf(invoice, user)
    except Exception as exc:
        logger.error("PDF generation failed: %s", exc)
        await notifier.pdf_failed(from_email, str(exc))
        return JSONResponse({"status": "error", "detail": "PDF generation failed"}, status_code=500)

    # 8. Send invoice to recipient
    recipient_email = result.recipient_email or from_email
    recipient_display = recipient_name or recipient_email

    await emailer.send_invoice(
        to_email=recipient_email,
        to_name=recipient_display,
        from_name=user.company_name or from_email,
        invoice_number=invoice_number,
        recipient_name=recipient_display,
        amount_czk=float(invoice.amount_total),
        pdf_bytes=pdf_bytes,
    )

    # Send copy to OSVČ
    await emailer.send_invoice_copy(
        user_email=from_email,
        invoice_number=invoice_number,
        recipient_name=recipient_display,
        amount_czk=float(invoice.amount_total),
        pdf_bytes=pdf_bytes,
    )

    invoice.status = InvoiceStatus.sent.value
    db.commit()

    # 9. Schedule reminders
    scheduler.schedule_reminders(invoice, db)

    # 10. Stripe charge
    if is_new_user:
        # First invoice is free; send welcome with setup link
        setup_url = f"{settings.base_url}/setup?token={user.setup_token}"
        await emailer.send_welcome(from_email, setup_url)
    elif user.stripe_customer_id:
        try:
            charge_id = stripe_handler.charge_for_invoice(user, invoice)
            invoice.stripe_charge_id = charge_id
            db.commit()
        except Exception as exc:
            logger.error("Stripe charge failed: %s", exc)
            invoice.status = InvoiceStatus.pending_payment.value
            db.commit()
            await notifier.payment_failed(invoice_number, from_email, str(exc))
    else:
        setup_url = f"{settings.base_url}/setup?token={user.setup_token}"
        stripe_handler.create_payment_link(user, invoice, setup_url)

    # 11. Telegram notification
    await notifier.invoice_sent(invoice_number, recipient_display, float(invoice.amount_total))

    return JSONResponse({"status": "ok", "invoice_number": invoice_number})


# ---------------------------------------------------------------------------
# Setup page (web onboarding)
# ---------------------------------------------------------------------------

@app.get("/setup", response_class=HTMLResponse)
async def setup_page(token: str, db: Session = Depends(get_db)) -> HTMLResponse:
    user = db.query(User).filter(User.setup_token == token).first()
    if not user:
        raise HTTPException(status_code=404, detail="Neplatný odkaz")

    stripe_setup_url = stripe_handler.create_setup_link(
        user, return_url=f"{settings.base_url}/setup?token={token}"
    )

    html = f"""
    <!DOCTYPE html><html lang="cs"><head><meta charset="UTF-8">
    <title>FakturoBot — Nastavení</title>
    <style>body{{font-family:Arial,sans-serif;max-width:480px;margin:60px auto;padding:20px}}
    h1{{font-size:22px}}a.btn{{display:inline-block;padding:12px 24px;background:#111;color:#fff;
    text-decoration:none;border-radius:6px;margin-top:16px}}</style></head>
    <body>
    <h1>Nastavení FakturoBot</h1>
    <p>Email: <strong>{user.email}</strong></p>
    <p>Pro automatické účtování 29 Kč/faktura přidejte platební kartu:</p>
    <a class="btn" href="{stripe_setup_url}">Přidat platební kartu</a>
    </body></html>
    """
    return HTMLResponse(html)


# ---------------------------------------------------------------------------
# Stripe webhook
# ---------------------------------------------------------------------------

@app.post("/stripe-webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    body = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe_handler.construct_webhook_event(body, sig)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "payment_intent.succeeded":
        intent = event["data"]["object"]
        invoice_id = intent.get("metadata", {}).get("invoice_id")
        if invoice_id:
            invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
            if invoice:
                invoice.stripe_charge_id = intent["id"]
                db.commit()

    elif event["type"] == "payment_intent.payment_failed":
        intent = event["data"]["object"]
        invoice_number = intent.get("metadata", {}).get("invoice_number", "unknown")
        invoice_id = intent.get("metadata", {}).get("invoice_id")
        error_msg = intent.get("last_payment_error", {}).get("message", "unknown")

        if invoice_id:
            invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
            if invoice:
                invoice.status = InvoiceStatus.pending_payment.value
                db.commit()
                user = invoice.user
                await notifier.payment_failed(invoice_number, user.email, error_msg)

    elif event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        customer_id = session.get("customer")
        if customer_id and session.get("mode") == "setup":
            user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
            if not user:
                # Match by email from Stripe customer
                stripe_customer = stripe.Customer.retrieve(customer_id)
                email = stripe_customer.get("email", "")
                user = db.query(User).filter(User.email == email).first()
            if user:
                user.stripe_customer_id = customer_id
                db.commit()

    return JSONResponse({"status": "ok"})
