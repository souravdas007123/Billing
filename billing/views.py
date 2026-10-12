import csv
import datetime
import json
import re
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .calc import D, amount_in_words, compute_invoice, q2, rate_summary, split_gst
from .reports import build_report, fy_label, fy_start_year
from .models import STATE_CODES, Firm, Invoice, InvoiceItem, Party, Product

MAX_ROWS = 500
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_AMOUNT = Decimal("99999999999")  # stays below the DB field limit (14,2)


# ---------------- helpers ----------------
def _plain(d):
    """Format a Decimal without trailing zeros: 100.0000 -> '100'."""
    return format(Decimal(d).normalize(), "f")


def _money(d):
    return format(d, ".2f")


def _load_json(request):
    try:
        return json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def _err(errors, status=400):
    return JsonResponse({"ok": False, "errors": errors}, status=status)


PRICE_MODES = ("AMT", "EXCL", "INCL")


def _price_mode(value):
    return value if value in PRICE_MODES else "EXCL"


def _is_intra(firm, place_of_supply):
    place = (place_of_supply or "").strip()
    return place == "" or place == firm.state


def _serialize(result):
    out = {k: _money(result[k]) for k in ("taxable", "cgst", "sgst", "igst", "gst_total", "round_off", "total")}
    out["words"] = result["words"]
    out["intra"] = result["intra"]
    out["summary"] = [{k: (_plain(v) if k == "rate" else _money(v)) for k, v in row.items()} for row in result["summary"]]
    out["lines"] = [{k: _money(q2(v) if k == "rate" else v) for k, v in line.items()} for line in result["lines"]]
    return out


def _decimals_ok(value, places):
    return value == value.quantize(Decimal(1).scaleb(-places))


# ---------------- live calculation ----------------
@login_required
@require_POST
def calc_api(request):
    data = _load_json(request)
    if not isinstance(data, dict):
        return _err(["The submitted data is not in a valid format."])
    items = data.get("items")
    if not isinstance(items, list) or len(items) > MAX_ROWS:
        return _err(["The items are not valid."])
    items = [i if isinstance(i, dict) else {} for i in items]
    firm = Firm.get()
    try:
        mode = _price_mode(data.get("price_mode"))
        result = compute_invoice(
            items,
            inclusive=mode == "INCL",
            intra=_is_intra(firm, data.get("place_of_supply")),
            amount_mode=mode == "AMT",
        )
    except ArithmeticError:
        return _err(["One of the amounts is too large."])
    return JsonResponse({"ok": True, **_serialize(result)})


# ---------------- validation of an invoice ----------------
def _clean_payload(data, firm):
    errors = []

    submitted = data.get("submitted") is not False  # only an explicit false means "give it later"
    # A bill that is not submitted yet gets no invoice number. For a submitted bill a blank number means "assign the next one".
    invoice_no = (data.get("invoice_no") or "").strip() if submitted else ""
    if len(invoice_no) > 40:
        errors.append("Invoice number must be 40 characters or fewer.")

    try:
        date = datetime.date.fromisoformat((data.get("date") or "").strip())
    except ValueError:
        date = None
        errors.append("Enter a valid date.")

    party_name = (data.get("party_name") or "").strip()
    if not party_name:
        errors.append("Select a party or enter a party name.")
    elif len(party_name) > 200:
        errors.append("The party name is too long.")

    party_email = (data.get("party_email") or "").strip()
    if party_email and (len(party_email) > 254 or not EMAIL_RE.match(party_email)):
        errors.append("Enter a valid party email address.")
    party_state = (data.get("party_state") or "").strip()
    if party_state and party_state not in STATE_CODES:
        errors.append("Select a valid party state.")
    place = (data.get("place_of_supply") or "").strip() or party_state or firm.state
    if place not in STATE_CODES:
        errors.append("Select a valid place of supply.")

    price_mode = _price_mode(data.get("price_mode"))
    amount_mode = price_mode == "AMT"

    allowed_rates = set(settings.GST_RATES)
    rows = data.get("items")
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        errors.append("The items are not valid.")
        rows = []

    items = []
    for n, r in enumerate(rows, start=1):
        if not isinstance(r, dict):
            continue
        desc = str(r.get("description") or "").strip()
        qty_text = str(r.get("qty") or "").strip()
        rate_text = str(r.get("rate") or "").strip()
        amount_text = str(r.get("amount") or "").strip()
        if not desc and not qty_text and not (amount_text if amount_mode else rate_text):
            continue  # skip empty lines
        label = f"Line {n}"
        qty = Decimal(1) if (amount_mode and qty_text == "") else D(qty_text)
        rate, amount = D(rate_text), D(amount_text)
        disc = Decimal(0) if amount_mode else D(r.get("discount_pct"))
        gst = D(r.get("gst_rate"))
        hsn, unit = str(r.get("hsn") or "").strip(), str(r.get("unit") or "").strip()

        if not desc:
            errors.append(f"{label}: enter the item name.")
        elif len(desc) > 300:
            errors.append(f"{label}: the item name is too long.")
        if qty <= 0 or qty >= Decimal(10) ** 10:
            errors.append(f"{label}: quantity must be greater than 0.")
        elif not _decimals_ok(qty, 3):
            errors.append(f"{label}: quantity can have at most 3 decimal places.")
        if amount_mode:
            if amount_text == "":
                errors.append(f"{label}: enter the amount.")
            elif amount <= 0 or amount >= Decimal(10) ** 9:
                errors.append(f"{label}: the amount must be greater than 0.")
            elif not _decimals_ok(amount, 2):
                errors.append(f"{label}: the amount can have at most 2 decimal places.")
        elif rate_text == "":
            errors.append(f"{label}: enter the rate.")
        elif rate < 0 or rate >= Decimal(10) ** 9:
            errors.append(f"{label}: the rate is not valid.")
        elif not _decimals_ok(rate, 4):
            errors.append(f"{label}: rate can have at most 4 decimal places.")
        if disc < 0 or disc > 100 or not _decimals_ok(disc, 2):
            errors.append(f"{label}: discount must be between 0 and 100 (at most 2 decimal places).")
        if gst not in allowed_rates:
            errors.append(f"{label}: select a GST rate from the list.")
        if len(hsn) > 12:
            errors.append(f"{label}: the HSN code is too long.")
        if len(unit) > 20:
            errors.append(f"{label}: the unit is too long.")

        items.append(
            {"description": desc, "hsn": hsn, "qty": qty, "unit": unit, "rate": rate, "amount": amount,
             "discount_pct": disc, "gst_rate": gst}
        )

    if not items and not errors:
        errors.append("Add at least one item.")
    if errors:
        return None, errors

    try:
        result = compute_invoice(
            items, inclusive=price_mode == "INCL", intra=_is_intra(firm, place), amount_mode=amount_mode
        )
    except ArithmeticError:
        return None, ["One of the amounts is too large."]
    if amount_mode:  # the rate is derived from the amount, so store the derived value
        for it, line in zip(items, result["lines"]):
            it["rate"] = line["rate"]
    if result["total"] > MAX_AMOUNT or any(l["total"] > MAX_AMOUNT for l in result["lines"]):
        return None, ["The invoice total is too large."]

    return {
        "invoice_no": invoice_no,
        "date": date,
        "party_name": party_name,
        "party_address": (data.get("party_address") or "").strip(),
        "party_gstin": (data.get("party_gstin") or "").strip().upper()[:15],
        "party_state": party_state,
        "party_phone": (data.get("party_phone") or "").strip()[:40],
        "party_email": party_email,
        "submitted": submitted,
        "place_of_supply": place,
        "price_mode": price_mode,
        "notes": (data.get("notes") or "").strip(),
        "items": items,
        "result": result,
    }, []


def _resolve_party(c):
    """Use the existing party if the name matches; otherwise create a new one (existing parties are never modified)."""
    party = Party.objects.filter(name__iexact=c["party_name"]).first()
    if party is None:
        party = Party.objects.create(
            name=c["party_name"], address=c["party_address"], gstin=c["party_gstin"],
            state=c["party_state"], phone=c["party_phone"], email=c["party_email"],
        )
    return party


# ---------------- save ----------------
@login_required
@require_POST
def invoice_save(request, pk=None):
    firm = Firm.get()
    data = _load_json(request)
    if not isinstance(data, dict):
        return _err(["The submitted data is not in a valid format."])
    c, errors = _clean_payload(data, firm)
    if errors:
        return _err(errors)

    invoice = get_object_or_404(Invoice, pk=pk) if pk else None
    was_issued = invoice is not None and invoice.invoice_no is not None
    if was_issued and not c["submitted"]:
        return _err(["This bill has already been submitted and its invoice number is in use, so it cannot go back to \"not submitted\"."])

    number = c["invoice_no"]
    if was_issued and not number:
        number = invoice.invoice_no  # a blank field on an existing invoice keeps its number
    dup_msg = [f"Invoice number {number} already exists. Enter a different number."]
    if number:
        dup = Invoice.objects.filter(invoice_no=number)
        if invoice:
            dup = dup.exclude(pk=invoice.pk)
        if dup.exists():
            return _err(dup_msg)

    # A submitted bill without a number (a new bill, or a draft being submitted) is given the next number in the series.
    auto_number = c["submitted"] and not number
    attempts = 3 if auto_number else 1
    r = c["result"]
    for attempt in range(attempts):
        try:
            with transaction.atomic():
                inv = invoice or Invoice()
                if not c["submitted"]:
                    inv.invoice_no = None
                else:
                    inv.invoice_no = number or Invoice.next_number(firm.invoice_prefix, c["date"])
                inv.date = c["date"]
                inv.party = _resolve_party(c)
                inv.party_name = c["party_name"]
                inv.party_address = c["party_address"]
                inv.party_gstin = c["party_gstin"]
                inv.party_state = c["party_state"]
                inv.party_phone = c["party_phone"]
                inv.party_email = c["party_email"]
                inv.place_of_supply = c["place_of_supply"]
                inv.price_mode = c["price_mode"]
                inv.is_intra_state = r["intra"]
                inv.taxable_value = r["taxable"]
                inv.cgst, inv.sgst, inv.igst = r["cgst"], r["sgst"], r["igst"]
                inv.round_off = r["round_off"]
                inv.total = r["total"]
                inv.notes = c["notes"]
                if not c["submitted"]:
                    inv.submitted_on = None
                elif inv.submitted_on is None:
                    inv.submitted_on = timezone.localdate()
                inv.save()
                if invoice:
                    inv.items.all().delete()
                InvoiceItem.objects.bulk_create(
                    [
                        InvoiceItem(
                            invoice=inv, sr=i, description=it["description"], hsn=it["hsn"], qty=it["qty"],
                            unit=it["unit"], rate=it["rate"], discount_pct=it["discount_pct"],
                            gst_rate=it["gst_rate"], taxable=line["taxable"], gst_amount=line["gst"],
                            line_total=line["total"],
                        )
                        for i, (it, line) in enumerate(zip(c["items"], r["lines"]), start=1)
                    ]
                )
            break
        except IntegrityError:
            if attempt == attempts - 1:
                return _err(["Could not assign an invoice number. Please try again."] if auto_number else dup_msg)

    return JsonResponse({"ok": True, "id": inv.pk, "print_url": reverse("invoice_print", args=[inv.pk])})


# ---------------- invoice number helpers ----------------
def _last_invoice(current=None):
    """The most recently created invoice (other than the one being edited), for the hint under the number field."""
    qs = Invoice.objects.filter(invoice_no__isnull=False).order_by("-id")  # drafts have no number
    if current is not None:
        qs = qs.exclude(pk=current.pk)
    last = qs.first()
    if last is None:
        return None
    return {"no": last.invoice_no, "date": last.date.strftime("%d-%m-%Y"), "party": last.party_name}


@login_required
def check_number(request):
    """Tell the billing screen whether an invoice number is already used, while the user types it."""
    number = (request.GET.get("no") or "").strip()
    if not number:
        return JsonResponse({"exists": False})
    qs = Invoice.objects.filter(invoice_no=number)
    exclude = request.GET.get("exclude") or ""
    if exclude.isdigit():
        qs = qs.exclude(pk=int(exclude))
    found = qs.first()
    if found is None:
        return JsonResponse({"exists": False})
    return JsonResponse({"exists": True, "date": found.date.strftime("%d-%m-%Y"), "party": found.party_name})


# ---------------- pages ----------------
@login_required
def invoice_form(request, pk=None):
    firm = Firm.get()
    invoice = get_object_or_404(Invoice.objects.prefetch_related("items"), pk=pk) if pk else None

    if invoice:
        inv = {
            "invoice_no": invoice.invoice_no or "",
            "date": invoice.date.isoformat(),
            "price_mode": invoice.price_mode,
            "party_name": invoice.party_name,
            "party_address": invoice.party_address,
            "party_gstin": invoice.party_gstin,
            "party_state": invoice.party_state,
            "party_phone": invoice.party_phone,
            "party_email": invoice.party_email,
            "place_of_supply": invoice.place_of_supply,
            "notes": invoice.notes,
            "pending": invoice.is_draft,
            "issued": not invoice.is_draft,
            "items": [
                {"description": i.description, "hsn": i.hsn, "qty": _plain(i.qty), "unit": i.unit,
                 "rate": _plain(i.rate), "amount": _plain(i.line_total),
                 "discount_pct": _plain(i.discount_pct), "gst_rate": _plain(i.gst_rate)}
                for i in invoice.items.all()
            ],
        }
    else:
        today = timezone.localdate()
        inv = {
            "invoice_no": Invoice.next_number(firm.invoice_prefix, today),
            "date": today.isoformat(),
            "price_mode": "AMT",
            "party_name": "", "party_address": "", "party_gstin": "", "party_state": "",
            "party_phone": "", "party_email": "", "place_of_supply": "", "notes": "", "pending": False, "issued": False, "items": [],
        }

    init = {
        "save_url": reverse("invoice_update", args=[invoice.pk]) if invoice else reverse("invoice_save"),
        "calc_url": reverse("calc_api"),
        "new_url": reverse("invoice_new"),
        "check_url": reverse("check_number"),
        "invoice_id": invoice.pk if invoice else None,
        "next_number": Invoice.next_number(firm.invoice_prefix, timezone.localdate()),
        "today": timezone.localdate().isoformat(),
        "last_invoice": _last_invoice(invoice),
        "firm_state": firm.state,
        "state_codes": STATE_CODES,
        "gst_rates": [_plain(r) for r in settings.GST_RATES],
        "units": list(getattr(settings, "UNITS", ["Nos"])),
        "default_gst": _plain(settings.DEFAULT_GST_RATE),
        "parties": list(Party.objects.values("id", "name", "address", "gstin", "state", "phone", "email")),
        "products": [
            {"name": p.name, "hsn": p.hsn, "unit": p.unit, "rate": _plain(p.rate), "gst_rate": _plain(p.gst_rate)}
            for p in Product.objects.all()
        ],
        "invoice": inv,
    }
    return render(request, "billing/invoice_form.html", {"init": init, "editing": invoice})


@login_required
def invoice_list(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    status = status if status in ("pending", "submitted") else ""
    qs = Invoice.objects.all()
    if q:
        qs = qs.filter(Q(invoice_no__icontains=q) | Q(party_name__icontains=q) | Q(party_gstin__icontains=q))
    if status == "pending":
        qs = qs.filter(submitted_on__isnull=True)
    elif status == "submitted":
        qs = qs.filter(submitted_on__isnull=False)
    pending_count = Invoice.objects.filter(submitted_on__isnull=True).count()
    total_count = Invoice.objects.count()
    counts = {"all": total_count, "pending": pending_count, "submitted": total_count - pending_count}
    return render(
        request,
        "billing/invoice_list.html",
        {"invoices": qs[:200], "q": q, "status": status, "counts": counts},
    )


@login_required
@require_POST
def invoice_submit(request, pk):
    """Submit a draft: it is given the next invoice number in the series and today's date (if its date is in the past)."""
    invoice = get_object_or_404(Invoice, pk=pk)
    if invoice.invoice_no is None:
        firm = Firm.get()
        today = timezone.localdate()
        for attempt in range(3):
            try:
                with transaction.atomic():
                    invoice.date = max(invoice.date, today)  # the invoice date is the day it is issued
                    invoice.invoice_no = Invoice.next_number(firm.invoice_prefix, invoice.date)
                    invoice.submitted_on = today
                    invoice.save()
                break
            except IntegrityError:  # another bill took this number a moment ago: try the next one
                invoice.invoice_no = None
                invoice.submitted_on = None
    target = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        target = reverse("invoice_list")
    return HttpResponseRedirect(target)


def _stored_summary(invoice, items):
    """Tax summary by rate for a saved invoice, from its stored lines (same rounding rule as when it was calculated)."""
    entries = []
    for it in items:
        cgst, sgst, igst = split_gst(it.gst_amount, invoice.is_intra_state)
        entries.append((it.gst_rate, {"taxable": it.taxable, "gst": it.gst_amount, "cgst": cgst, "sgst": sgst, "igst": igst}))
    return rate_summary(entries)


def _print_lines(invoice, items):
    """The invoice lines for printing, each with its own CGST / SGST (or IGST) split like when it was calculated."""
    out = []
    for it in items:
        cgst, sgst, igst = split_gst(it.gst_amount, invoice.is_intra_state)
        out.append({
            "sr": it.sr, "description": it.description, "hsn": it.hsn, "qty": it.qty, "unit": it.unit, "rate": it.rate,
            "discount_pct": it.discount_pct, "gst_rate": it.gst_rate, "half_rate": it.gst_rate / 2, "taxable": it.taxable,
            "gst_amount": it.gst_amount, "cgst": cgst, "sgst": sgst, "igst": igst, "line_total": it.line_total,
        })
    return out


@login_required
def invoice_print(request, pk):
    invoice = get_object_or_404(Invoice.objects.prefetch_related("items"), pk=pk)
    firm = Firm.get()
    return render(
        request,
        "billing/invoice_print.html",
        {
            "invoice": invoice,
            "items": _print_lines(invoice, invoice.items.all()),
            "firm": firm,
            "firm_state_code": STATE_CODES.get(firm.state, ""),
            "pos_code": STATE_CODES.get(invoice.place_of_supply, ""),
            "words": amount_in_words(invoice.total),
            "inclusive": invoice.price_mode == "INCL",
            "summary": _stored_summary(invoice, invoice.items.all()),
        },
    )


def _report_for_year(request):
    """The sales report of the financial year chosen with ?fy=2026 (default: the current one). Submitted bills only."""
    today = timezone.localdate()
    try:
        start = int(request.GET.get("fy", ""))
        if not 2000 <= start <= 2100:
            raise ValueError
    except ValueError:
        start = fy_start_year(today)
    begin, end = datetime.date(start, 4, 1), datetime.date(start + 1, 3, 31)
    issued = Invoice.objects.filter(invoice_no__isnull=False, date__gte=begin, date__lte=end)
    invoices = list(issued.values("date", "party_name", "is_intra_state", "taxable_value", "cgst", "sgst", "igst", "round_off", "total"))
    items = list(
        InvoiceItem.objects.filter(invoice__in=issued).values("gst_rate", "taxable", "gst_amount")
    )
    return start, today, build_report(invoices, items, start, today)


@login_required
def dashboard(request):
    start, today, report = _report_for_year(request)
    years = {fy_start_year(d) for d in Invoice.objects.filter(invoice_no__isnull=False).dates("date", "month")}
    years |= {fy_start_year(today), start}
    drafts = Invoice.objects.filter(invoice_no__isnull=True)
    return render(
        request,
        "billing/dashboard.html",
        {
            "report": report,
            "fy": start,
            "fy_label": fy_label(start),
            "fy_options": [{"value": y, "label": fy_label(y)} for y in sorted(years, reverse=True)],
            "draft_count": drafts.count(),
            "draft_total": sum((d for d in drafts.values_list("total", flat=True)), Decimal("0.00")),
        },
    )


@login_required
def dashboard_export(request):
    """Monthly summary as a CSV file (opens in Excel) - handy for the CA / GST return."""
    start, today, report = _report_for_year(request)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="sales-summary-FY{fy_label(start)}.csv"'
    response.write("\ufeff")  # so Excel reads the file as UTF-8
    w = csv.writer(response)
    w.writerow(["Month", "Bills", "Taxable value", "CGST", "SGST", "IGST", "Total GST", "Round off", "Invoice total"])
    for m in report["months"] + [report["totals"]]:
        w.writerow([m["label"], m["bills"], m["taxable"], m["cgst"], m["sgst"], m["igst"], m["gst"], m["round_off"], m["total"]])
    return response
