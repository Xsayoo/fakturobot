import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from models import Invoice, InvoiceStatus, Reminder, ReminderType

logger = logging.getLogger(__name__)

_scheduler = BackgroundScheduler()


def start(db_factory) -> None:
    _scheduler.add_job(
        func=_check_reminders,
        trigger="interval",
        hours=6,
        id="reminder_check",
        replace_existing=True,
        kwargs={"db_factory": db_factory},
    )
    _scheduler.start()
    logger.info("Scheduler started")


def stop() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)


def schedule_reminders(invoice: Invoice, db: Session) -> None:
    if not invoice.due_date:
        return

    offsets = [
        (ReminderType.day7, 7),
        (ReminderType.day14, 14),
        (ReminderType.day30, 30),
    ]
    for reminder_type, days in offsets:
        scheduled_for = invoice.due_date + timedelta(days=days)
        reminder = Reminder(
            invoice_id=invoice.id,
            scheduled_for=scheduled_for,
            reminder_type=reminder_type.value,
        )
        db.add(reminder)

    db.commit()
    logger.info("Scheduled reminders for invoice %s", invoice.invoice_number)


def cancel_reminders(invoice: Invoice, db: Session) -> None:
    for reminder in invoice.reminders:
        if reminder.sent_at is None:
            db.delete(reminder)
    db.commit()
    logger.info("Cancelled pending reminders for invoice %s", invoice.invoice_number)


def _check_reminders(db_factory) -> None:
    import asyncio

    from emailer import send_reminder
    from generator import generate_pdf

    db: Session = db_factory()
    now = datetime.now(timezone.utc)

    try:
        due = (
            db.query(Reminder)
            .join(Invoice)
            .filter(
                Reminder.sent_at.is_(None),
                Reminder.scheduled_for <= now,
                Invoice.status.in_([InvoiceStatus.sent.value, InvoiceStatus.overdue.value]),
            )
            .all()
        )

        for reminder in due:
            invoice = reminder.invoice
            user = invoice.user

            try:
                pdf_bytes = None
                if reminder.reminder_type == ReminderType.day7.value:
                    pdf_bytes = generate_pdf(invoice, user)

                to_email = invoice.recipient_email or user.email

                asyncio.run(
                    send_reminder(
                        to_email=to_email,
                        invoice_number=invoice.invoice_number,
                        amount_czk=float(invoice.amount_total),
                        due_date=invoice.due_date.strftime("%d. %m. %Y"),
                        reminder_type=reminder.reminder_type,
                        pdf_bytes=pdf_bytes,
                    )
                )

                reminder.sent_at = now
                if invoice.status == InvoiceStatus.sent.value:
                    invoice.status = InvoiceStatus.overdue.value

                db.commit()
                logger.info(
                    "Reminder %s sent for invoice %s",
                    reminder.reminder_type,
                    invoice.invoice_number,
                )

            except Exception as exc:
                logger.error("Failed to send reminder %s: %s", reminder.id, exc)
                db.rollback()

    finally:
        db.close()
