# Office Billing (Django)

A simple app for creating invoices. Pick a party, paste the items from Excel, choose the GST rate, and everything else is calculated for you.

## First-time setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows   (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt

python manage.py migrate
python manage.py createsuperuser      # this will be your login
python manage.py runserver
```

Open http://127.0.0.1:8000/ in your browser.

To use it from other computers in the office, run `python manage.py runserver 0.0.0.0:8000`
and open `http://<this computer's IP address>:8000/` on the other machines.

## One-time setup in the admin site (http://127.0.0.1:8000/admin/)

1. **Firm**: your company name, address, GSTIN, **state**, bank details, terms and invoice prefix.
   The state must be correct, because it decides whether CGST + SGST or IGST is charged.
2. **Parties**: your customers. You can also just type a new name while creating an invoice and it is saved automatically.
3. **Products** (optional): when you type an item name, its HSN, unit, rate and GST % are filled in automatically.

## Creating an invoice

- **Invoice number** is generated automatically (for example `INV/26-27/0001`) and restarts every financial year (April to March). You can edit it.
- **Party**: selecting one fills in the address, GSTIN, state and phone. The place of supply follows the party's state.
- **Items**: copy rows from Excel, then press Ctrl+V anywhere on the page. First choose the column order
  (for example `Item | Qty | Rate`). A header row is skipped automatically.
- **GST rate**: choose it once at the top and it applies to every line. Change a single line to give it a different rate.
- **GST included / excluded**: one dropdown switches the whole calculation.
- Totals, CGST / SGST / IGST, round-off and the amount in words update live.
- **Ctrl+S** saves and opens the print page, where you can print or save a PDF.

## How the numbers are calculated

- The final calculation always happens on the server in `billing/calc.py`, using Decimal (never floats). What you see on screen is exactly what is saved.
- GST excluded: GST is added on top of the taxable value. GST included: the GST is taken out of the rate, and the line total stays equal to what the rate gives.
- GST is rounded per line, and CGST + SGST always add up to the GST. The invoice total is rounded to the nearest rupee.
- The party's details are copied onto the invoice, so editing a party later does not change old invoices.
- Invalid entries (quantity 0, a missing rate, a GST rate outside the list, a duplicate invoice number) are rejected before saving.
- The GSTIN checksum is verified (it shows a warning but does not block saving).

## Changing the GST rates

Edit `GST_RATES` and `DEFAULT_GST_RATE` in `config/settings.py`. Use the rates your accountant confirms.

## Backups

All data is stored in the `db.sqlite3` file, which is not tracked by git. Copy it to another location every day.

## Tests

```bash
python manage.py test                 # everything
python -m unittest billing.test_calc  # only the calculation tests (no Django needed)
```

## Running in production

Set `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0` and `DJANGO_ALLOWED_HOSTS=your-ip-or-domain`, and use a server such as
waitress or gunicorn instead of `runserver`. With `DEBUG=0`, the admin site needs a static-file setup such as
`whitenoise` (`python manage.py collectstatic`). For use only inside the office LAN, `runserver` is enough.
