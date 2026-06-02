import base64
import io
import logging
from datetime import datetime
from pathlib import Path

import qrcode
import qrcode.constants
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

from models import Invoice, User

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _qr_payment_data_uri(iban: str, amount: float, variable_symbol: str, message: str) -> str:
    qr_string = (
        f"SPD*1.0*ACC:{iban}*AM:{amount:.2f}*CC:CZK"
        f"*X-VS:{variable_symbol}*MSG:{message[:35]}"
    )
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=2,
    )
    qr.add_data(qr_string)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def generate_pdf(invoice: Invoice, user: User) -> bytes:
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=True)
    template = env.get_template("faktura.html")

    qr_data_uri = None
    if user.bank_account:
        vs = invoice.invoice_number.replace("-", "")[-10:]
        try:
            qr_data_uri = _qr_payment_data_uri(
                iban=user.bank_account,
                amount=float(invoice.amount_total),
                variable_symbol=vs,
                message=f"Faktura {invoice.invoice_number}",
            )
        except Exception as exc:
            logger.warning("QR code generation failed: %s", exc)

    html_content = template.render(
        invoice=invoice,
        user=user,
        qr_data_uri=qr_data_uri,
        now=datetime.now(),
    )

    return HTML(string=html_content, base_url=str(_TEMPLATES_DIR)).write_pdf()
