# Fakturace-as-a-Service — Master Build Prompt

## Co stavíme
Plně automatizovaný fakturační agent pro české OSVČ.
OSVČ pošle email → systém vytvoří PDF fakturu → odešle ji klientovi → účtuje 29 Kč přes Stripe.
Žádný dashboard, žádná registrace, žádný manuální krok.

## Tech stack
- **Framework:** FastAPI (Python 3.11+)
- **AI parsing:** Anthropic Claude API (claude-sonnet-4-20250514)
- **PDF:** WeasyPrint + Jinja2 šablona
- **Email příjem:** Postmark Inbound webhook
- **Email odesílání:** Postmark Outbound (transactional)
- **Databáze:** PostgreSQL přes SQLAlchemy (Supabase free tier v produkci)
- **Platby:** Stripe (saved cards, pay-per-use 29 Kč/faktura)
- **Notifikace:** Telegram Bot API
- **Upomínky:** APScheduler (7, 14, 30 dní po splatnosti)
- **IČO lookup:** ARES API (zdarma, bez klíče)
- **Hosting:** Railway.app

## Struktura projektu
```
fakturace-agent/
├── app.py              # FastAPI, webhook endpoint /inbound
├── parser.py           # Claude API → InvoiceData dataclass
├── generator.py        # WeasyPrint → bytes PDF
├── emailer.py          # Postmark send/receive wrapper
├── scheduler.py        # APScheduler, upomínky
├── models.py           # SQLAlchemy: User, Invoice, Reminder
├── stripe_handler.py   # Stripe checkout, webhooks
├── ares.py             # ARES API lookup podle IČO
├── notifier.py         # Telegram notifikace pro Jakuba
├── templates/
│   └── faktura.html    # Česká faktura šablona (HTML → PDF)
├── .env.example        # Seznam potřebných proměnných
├── requirements.txt
├── railway.json        # Deploy config
└── tests/
    ├── test_parser.py
    └── test_generator.py
```

## Datové modely (models.py)

### User
- id, email (PK de facto), created_at
- stripe_customer_id (null dokud nepřidá kartu)
- invoice_email (kam posílat faktury — default = odesílatel)
- company_name, ico, dic (optional, pro hlavičku faktur)
- logo_url (optional)
- is_vat_payer (bool) — plátce i neplátce DPH

### Invoice
- id (UUID), user_id (FK)
- recipient_name, recipient_email, recipient_ico (optional)
- amount_czk (Decimal), vat_rate (0 / 21 / 15 / 10)
- description (text)
- invoice_number (auto-generovaný: YYYY-XXXX)
- issued_at, due_date (default: issued_at + 14 dní)
- status: draft | sent | paid | overdue | cancelled
- pdf_path (local) / pdf_url (po uploadu)
- stripe_charge_id
- raw_email_text (pro audit)

### Reminder
- id, invoice_id (FK), scheduled_for, sent_at, reminder_type (7d/14d/30d)

## Hlavní flow (app.py → /inbound)

```
POST /inbound (Postmark webhook)
  │
  ├─ 1. Parsuj email (emailer.py) → raw text
  │
  ├─ 2. Najdi nebo vytvoř User podle from_email (models.py)
  │     └─ Pokud nový: ulož, pošli welcome email se Stripe setup linkem
  │
  ├─ 3. Claude API (parser.py) → InvoiceData
  │     Prompt: extrahuj recipient, amount, currency, description, due_days, vat_rate
  │     Pokud chybí povinná pole: pošli OSVČ zpět "Upřesni prosím: ..."
  │
  ├─ 4. ARES lookup (ares.py) — pokud email obsahuje IČO
  │     → auto-doplní název firmy a adresu
  │
  ├─ 5. Generuj PDF (generator.py)
  │     WeasyPrint + templates/faktura.html
  │     QR kód platby (qrplatba standard)
  │
  ├─ 6. Odešli fakturu (emailer.py)
  │     → příjemci (PDF příloha)
  │     → kopie OSVČ ("Faktura odeslána ✓")
  │
  ├─ 7. Naplánuj upomínky (scheduler.py)
  │     APScheduler: +7d, +14d, +30d od due_date
  │
  ├─ 8. Účtuj 29 Kč (stripe_handler.py)
  │     Pokud saved card → charge immediately
  │     Pokud no card → pošli Stripe payment link (první faktura zdarma jako trial)
  │
  └─ 9. Telegram notifikace (notifier.py)
        "✅ Faktura #2024-0001 | Novák s.r.o. | 15 000 Kč | odesláno"
```

## parser.py — Claude API prompt

```python
SYSTEM_PROMPT = """Jsi pomocník pro zpracování fakturačních emailů.
Extrahuj z emailu strukturovaná data. Odpověz POUZE validním JSON, žádný text navíc.

JSON schema:
{
  "recipient_name": "string nebo null",
  "recipient_email": "string nebo null", 
  "recipient_ico": "string nebo null",
  "amount": number (bez DPH),
  "currency": "CZK",
  "description": "string",
  "due_days": number (default 14),
  "vat_rate": 0 nebo 21 nebo 15 nebo 10 (default 0 pro neplátce)
}

Pokud nelze určit amount nebo description, vrať: {"error": "missing_field", "missing": ["pole1"]}
"""
```

## templates/faktura.html
Česká faktura musí obsahovat:
- Číslo faktury (YYYY-XXXX formát)
- Dodavatel: jméno/firma, adresa, IČO, DIČ (pokud plátce)
- Odběratel: jméno/firma, adresa, IČO
- Datum vystavení, datum splatnosti
- Položky: popis, množství, cena bez DPH, DPH sazba, cena s DPH
- Celková částka (výrazně)
- Číslo účtu / IBAN pro platbu
- QR kód platby (qrplatba.cz standard)
- Footer: "Faktura vystavena systémem fakturace.ai"
Styl: čistý, profesionální, černobílý tisk OK, font Arial/sans-serif

## .env.example (Jakub dodá hodnoty)
```
# Anthropic
ANTHROPIC_API_KEY=

# Postmark
POSTMARK_SERVER_TOKEN=
POSTMARK_FROM_EMAIL=faktura@tvoje-domena.cz
INBOUND_EMAIL=prijem@tvoje-domena.cz

# Stripe
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
INVOICE_PRICE_CZK=29

# Database
DATABASE_URL=postgresql://...

# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# App
BASE_URL=https://tvoje-app.railway.app
SECRET_KEY=
```

## railway.json
```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": { "builder": "NIXPACKS" },
  "deploy": {
    "startCommand": "uvicorn app:app --host 0.0.0.0 --port $PORT",
    "healthcheckPath": "/health",
    "restartPolicyType": "ON_FAILURE"
  }
}
```

## Registrace zákazníka — dvě cesty

### A) Auto-registrace (primary flow)
1. Přijde email od nového uživatele
2. Systém vytvoří User záznam automaticky
3. Pošle welcome email s Stripe setup linkem ("Přidejte kartu pro příští faktury, první je zdarma")
4. První faktura se vygeneruje a odešle IHNED bez platby (trial)
5. Od druhé faktury = 29 Kč/ks z uložené karty

### B) Web formulář (secondary — onboarding pro nastavení)
- Jednoduchá stránka: `/setup?token=XXX` (token přijde v welcome emailu)
- Pole: logo upload, číslo účtu/IBAN, podpis, výchozí splatnost, DIČ
- Po vyplnění = faktury obsahují logo a kompletní údaje
- Stripe karta se přidá zde (embedded checkout)

## Stripe flow
- Model: pay-per-invoice (29 Kč za každou odeslanou fakturu)
- Stripe Customer vytvoř při první registraci
- Po úspěšném odeslání faktury: `stripe.PaymentIntent.create(amount=2900, currency="czk")`
- Webhook `/stripe-webhook`: zpracuj `payment_intent.succeeded` a `payment_intent.payment_failed`
- Při neúspěchu: Telegram alert Jakubovi + email OSVČ

## Upomínky (scheduler.py)
- APScheduler BackgroundScheduler, interval check každých 6 hodin
- Upomínka 1 (7 dní): zdvořilá, přiložit PDF znovu
- Upomínka 2 (14 dní): důraznější, zmínit penále (pokud OSVČ nastaví)
- Upomínka 3 (30 dní): finální, doporučit právní kroky
- Po zaplacení (webhook nebo manuální mark): cancel všechny pending reminders

## Error handling
- Neparsovatelný email → pošli OSVČ: "Nepodařilo se zpracovat. Zkus: 'Fakturuj [firma] [částka] Kč za [popis]'"
- Stripe selhání → Telegram alert, email OSVČ, faktura označena jako `pending_payment`
- ARES timeout → pokračuj bez dat (nejsou povinná)
- PDF generování selhání → Telegram alert, fallback na plain-text fakturu emailem

## Testy (tests/)
- `test_parser.py`: 10 různých formátů emailů, ověř správné parsování
- `test_generator.py`: vygeneruj testovací PDF, ověř že obsahuje povinné položky
- Spouštět: `pytest tests/ -v`

## Pořadí buildování
1. ✅ `models.py` + `requirements.txt` + `.env.example`
2. ✅ `ares.py` (jednoduché, testovatelné)
3. ✅ `parser.py` (Claude API, otestuj na 5 emailech)
4. ✅ `templates/faktura.html` (statická preview v browseru)
5. ✅ `generator.py` (WeasyPrint, vygeneruj testPDF)
6. ✅ `emailer.py` (Postmark, otestuj send)
7. ✅ `stripe_handler.py` (test mode)
8. ✅ `notifier.py` (Telegram)
9. ✅ `scheduler.py` (APScheduler)
10. ✅ `app.py` — všechno sešij dohromady
11. ✅ `tests/` — otestuj celý flow
12. ✅ `railway.json` + deploy

## Definition of Done
- [x] Email přijat → faktura odeslána do 60 sekund — `app.py /inbound` zpracuje celý flow synchronně
- [x] PDF obsahuje QR kód platby — `generator.py` generuje QR Platba (SPD standard) jako base64 PNG
- [x] Stripe účtuje 29 Kč po odeslání — `stripe_handler.charge_for_invoice()` v `app.py` po `invoice.status = sent`
- [x] Telegram notifikace přijde Jakubovi — `notifier.invoice_sent()` na konci každého `/inbound`
- [x] Upomínky naplánované — `scheduler.schedule_reminders()` naplánuje +7d/+14d/+30d od due_date
- [x] Nový zákazník dostane welcome email se setup linkem — `emailer.send_welcome()` při `is_new_user`
- [x] `/health` endpoint vrací 200 — implementováno v `app.py`
- [x] Všechny testy zelené — `test_parser.py` 12/12 passed; `test_generator.py` vyžaduje GTK3 na Windows (`C:\Program Files\GTK3-Runtime Win64\bin` v PATH), na Railway/Linux funguje bez konfigurace
