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
- **Mixed GST rates**: each line is calculated with its own rate and the invoice totals are the sum of the lines. When a bill
  has more than one rate, a *Tax summary by GST rate* (taxable value, CGST / SGST or IGST, GST per rate) is shown under the
  totals on the billing screen and on the printed invoice. Its columns always add up to the invoice totals.
- **Unit** is a drop-down (list in `config/settings.py` -> `UNITS`; a unit that comes from pasted rows or a product is added
  automatically). On the printed invoice an empty discount shows `-` and GST / discount values carry a `%` sign.
- **Document type** (top of the billing screen):
  - *Tax invoice*: the normal GST bill. If the party has no GSTIN, leave the field empty: the bill is issued to an
    unregistered party and prints "GSTIN: Unregistered". The dashboard shows registered (B2B) and unregistered (B2C) sales.
  - *Bill of supply (no GST)*: for a composition dealer or exempt goods. No GST columns, printed as "BILL OF SUPPLY",
    numbers `BOS/26-27/0001`. It counts as a sale on the dashboard (taxable value, 0 GST).
  - *Estimate*: not a tax document. Printed as "ESTIMATE", numbers `EST/26-27/0001`, and left out of every dashboard figure.
  Each type has its own number series, so the tax invoice series never has gaps. The type can be changed while a bill is
  a draft; once it has a number it is fixed. For a composition dealer, add the legally required wording (for example
  "Composition taxable person, not eligible to collect tax on supplies") to the Terms in Admin -> Firm.
- **Cancel a bill**: open the bill and press *Cancel invoice*, then give a reason. Only users with the
  `billing.cancel_invoice` permission (superusers have it; give it to others in Admin -> Users) can do this. A cancelled
  bill keeps its number (so the series has no hole), is stamped CANCELLED when printed, and is left out of the dashboard.
  A numbered bill can never be deleted (not even in the admin site); only a draft can be deleted.
- **Credit note** (document type *Credit note*): used when goods are returned or the price/tax of an earlier invoice must be
  reduced. Enter the original invoice number and date. It has its own series (`CN/26-27/0001`) and is **deducted** from the
  dashboard sales and GST. Use the *Credit note* button on the print page of an invoice to start one with the items filled in.
- The **Copy** button repeats a bill for the same party with today's date and a fresh number. the **Make tax invoice** button on an
  estimate (or bill of supply) copies it into a new Tax invoice; GST is added on top of the prices, so check the GST rate of
  each line before saving.
- **All invoices** can be filtered by text, document type and date range (the filters stay when you switch tabs or pages),
  and is shown 50 bills per page.
- **Ctrl+S** saves and opens the print page, where you can print or save a PDF.

## How the numbers are calculated

- The final calculation always happens on the server in `billing/calc.py`, using Decimal (never floats). What you see on screen is exactly what is saved.
- Amount entry: the line total is exactly the amount you typed. The taxable value and GST are taken out of it, and the rate is the taxable value divided by the quantity.
- GST excluded: GST is added on top of the taxable value. GST included: the GST is taken out of the rate, and the line total stays equal to what the rate gives.
- GST is rounded per line. On a same-state bill CGST and SGST are always **exactly equal** (the half is rounded first). When
  you type an amount with GST included, the amount never changes and the taxable value takes any odd paisa. The invoice
  total is rounded to the nearest rupee. Bills saved before this rule keep the figures they were saved with.
- The party's details are copied onto the invoice, so editing a party later does not change old invoices.
- Invalid entries (quantity 0, a missing rate or amount, a GST rate outside the list, a duplicate invoice number) are rejected before saving.
- The GSTIN checksum is verified (it shows a warning but does not block saving).

## Logo, signature, UPI QR and sharing

- Admin -> Firm -> *Print*: upload a **logo**, a company **stamp** and a **signature** (PNG or JPG, up to 1 MB each; they are stored in the `media/`
  folder) and enter your **UPI ID** (for example `shopname@okaxis`). The logo prints at the top, the signature above
  "Authorised signatory", and the stamp sits exactly in the middle between the bank details and the signature, and tax invoices / bills of supply get a **Pay by UPI** QR with the bill total. There is no QR on
  drafts, cancelled bills, estimates and credit notes. The QR needs the `segno` package (`pip install -r requirements.txt`);
  without it the bill simply prints without a QR.
- On a numbered bill the **WhatsApp** and **Email** buttons open WhatsApp / your mail app with a ready message to the party's
  phone or e-mail. Use *Print / save as PDF* first and attach the PDF yourself (the web cannot attach files automatically).

## GST reports and party statement

*GST reports* (top menu) gives, for a financial year or one month, CSV files for your GST return / CA: **B2B** (invoices and
credit notes to registered buyers, rate-wise), **B2C** (unregistered buyers by place of supply and rate, net of credit notes)
and an **HSN summary**. CGST and SGST are always equal halves. Only numbered, not-cancelled bills are included; estimates never.
The *Documents issued* table lists every number series with first/last number, cancelled numbers and any **missing numbers**
(these must be explained in the return). *Party statement* lists one party's bills for the year with a running total
(credit notes deducted); it can be printed or downloaded. Payments are not tracked, so it is a statement of bills only.

## Importing many parties at once

Admin -> Parties -> **Import parties**. Upload an Excel (.xlsx) or CSV file, or copy the rows in Excel (with the heading
row) and paste them into the box. Headings such as `name, address, gstin, state, phone, email` are understood (also
"Party Name", "GST No", "Mobile" and similar); only *name* is required. A preview shows what will be added, skipped or has
a problem, and nothing is saved until you press the import button. A party that already exists (same name) is skipped, or
updated with the filled cells only (an empty cell never erases saved details). A blank state is taken from the GSTIN.
Reading .xlsx files needs `openpyxl` (`pip install -r requirements.txt`).

## Changing the GST rates

Edit `GST_RATES` and `DEFAULT_GST_RATE` in `config/settings.py`. Use the rates your accountant confirms.

## Backups and audit log

- The database is copied automatically **once a day** (on the first page opened that day) to the `backups/` folder; the
  newest 30 copies are kept (`BACKUP_DIR`, `BACKUP_KEEP` in `config/settings.py`, or the `BILLING_BACKUP_DIR` environment
  variable). Point it to another disk or a synced folder if you can. `python manage.py backup --now` makes a fresh copy.
- A superuser sees a **Backup** button in the top bar that downloads the whole database as one file.
- The database runs in SQLite WAL mode, so recent changes can sit in `db.sqlite3-wal`. Do not copy `db.sqlite3` alone
  while the app is running; use the backups above (or stop the app first).
- To restore, stop the app, copy a backup over `db.sqlite3` (delete any `db.sqlite3-wal` / `-shm` files) and start it again.
- **Audit log** (Admin -> Audit logs, read-only): every create, edit (with the old and new total), submit, cancel, draft
  delete, party import and backup download, with the user and time.

## Tests

```bash
python manage.py test                 # everything
python -m unittest billing.test_calc billing.test_reports billing.test_importer  # only the calculation tests (no Django needed)
```

## Running in production

Set `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0` and `DJANGO_ALLOWED_HOSTS=your-ip-or-domain`, and use a server such as
waitress or gunicorn instead of `runserver`. With `DEBUG=0`, the admin site needs a static-file setup such as
`whitenoise` (`python manage.py collectstatic`). For use only inside the office LAN, `runserver` is enough.
