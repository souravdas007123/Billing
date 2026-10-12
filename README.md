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
- **Party**: selecting one fills in the address, GSTIN, state, phone and email. The place of supply follows the party's state.
  The email is optional, is checked for a valid format, and is printed in the "Bill to" box.
- **Items**: copy rows from Excel, then press Ctrl+V anywhere on the page. First choose the column order
  (for example `Item | Qty | Amount`). A header row is skipped automatically.
- **GST rate**: choose it once at the top and it applies to every line. Change a single line to give it a different rate.
- **Entry mode** (default: amount entry): type each line's **amount with GST included**, and the app works out the
  taxable value, GST and rate for you. A blank quantity counts as 1. Two other modes let you type the rate instead:
  *rate, GST excluded* (GST is added on top) and *rate, GST included*. Switching modes keeps each line's numbers.
  The printed invoice shows the derived rate (taxable value / quantity) without GST.
- Totals, CGST / SGST / IGST, round-off and the amount in words update live.
- **Invoice number**: under the field you can see the last invoice that was created, and as you type the app tells you
  whether the number is already used.
- **Bills you will hand over later**: tick "Not submitted yet" before saving. A draft has **no invoice number**, so it
  never uses up a number in the series (no gaps for GST). Use the **Not submitted** tab to see what is waiting and click
  **Submit & get number** (in the list or on the print page): the bill gets the next number in the series, and its date
  becomes today if it was in the past. A submitted bill cannot go back to a draft, and a draft can be edited freely or
  deleted without touching the numbering. Bills numbered before this feature existed are treated as already submitted
  (run `python manage.py migrate`).
- **Dashboard**: the *Dashboard* page shows, for the chosen financial year (April to March), the invoice total, taxable
  value and GST (CGST / SGST / IGST) month by month, a monthly chart, the top parties, a GST rate-wise table, same-state
  vs other-state sales, and how many bills are still not submitted. Only submitted bills are counted, by invoice date.
  **Download CSV** gives the monthly table for Excel / your CA.
- **Ctrl+S** saves and opens the print page, where you can print or save a PDF.

## How the numbers are calculated

- The final calculation always happens on the server in `billing/calc.py`, using Decimal (never floats). What you see on screen is exactly what is saved.
- Amount entry: the line total is exactly the amount you typed. The taxable value and GST are taken out of it, and the rate is the taxable value divided by the quantity.
- GST excluded: GST is added on top of the taxable value. GST included: the GST is taken out of the rate, and the line total stays equal to what the rate gives.
- GST is rounded per line, and CGST + SGST always add up to the GST. The invoice total is rounded to the nearest rupee.
- The party's details are copied onto the invoice, so editing a party later does not change old invoices.
- Invalid entries (quantity 0, a missing rate or amount, a GST rate outside the list, a duplicate invoice number) are rejected before saving.
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
