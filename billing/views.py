import csv
import datetime
import json
import re
from decimal import Decimal

from django.conf import settings
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.contrib import messages
from django.db.models import F, Q
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.http import require_POST

from .calc import D, amount_in_words, compute_invoice, q2, rate_summary, split_gst
from . import audit, share
from .gst_returns import b2b_rows, b2c_rows, hsn_rows, series_summary
from .reports import MONTH_NAMES as MONTH_LABELS, build_report, fy_label, fy_months, fy_start_year
from .models import DOC_TYPES, GST_DOC_TYPES, STATE_CODES, Firm, Invoice, InvoiceItem, Party, Product, doc_prefix

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


def _doc_type(value):
    return value if value in dict(DOC_TYPES) else "TAX"


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
    if _doc_type(data.get("doc_type")) not in GST_DOC_TYPES:  # no GST is charged on a bill of supply or an estimate
        items = [{**i, "gst_rate": "0"} for i in items]
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
    doc_type = _doc_type(data.get("doc_type"))
    ref_no, ref_date = "", None
    if doc_type == "CN":  # a credit note must say which invoice it corrects
        ref_no = (data.get("ref_no") or "").strip()
        if not ref_no or len(ref_no) > 40:
            errors.append("Enter the number of the invoice this credit note is against (up to 40 characters).")
        try:
            ref_date = datetime.date.fromisoformat((data.get("ref_date") or "").strip())
        except ValueError:
            errors.append("Enter the date of the invoice this credit note is against.")

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
        gst = D(r.get("gst_rate")) if doc_type in GST_DOC_TYPES else Decimal(0)  # only a tax invoice or credit note charges GST
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
        "doc_type": doc_type,
        "ref_no": ref_no,
        "ref_date": ref_date,
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
    if invoice is not None and invoice.is_cancelled:
        return _err(["A cancelled bill cannot be edited."])
    was_issued = invoice is not None and invoice.invoice_no is not None
    if was_issued and not c["submitted"]:
        return _err(["This bill has already been submitted and its invoice number is in use, so it cannot go back to \"not submitted\"."])

    if was_issued and c["doc_type"] != invoice.doc_type:
        return _err(["The type of a bill cannot be changed after it has been given an invoice number."])
    prefix = doc_prefix(firm, c["doc_type"])

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
    old_total = invoice.total if invoice is not None else None
    for attempt in range(attempts):
        try:
            with transaction.atomic():
                inv = invoice or Invoice()
                if not c["submitted"]:
                    inv.invoice_no = None
                else:
                    inv.invoice_no = number or Invoice.next_number(prefix, c["date"])
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
                inv.doc_type = c["doc_type"]
                inv.ref_no, inv.ref_date = c["ref_no"], c["ref_date"]
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

    what = "Created" if old_total is None else "Edited"
    detail = f"{inv.get_doc_type_display()}, {inv.party_name}, total {inv.total}" + (f" (was {old_total})" if old_total is not None and old_total != inv.total else "")
    audit.record(request, what if inv.invoice_no else what + " draft", inv.invoice_no or "", detail)
    return JsonResponse({"ok": True, "id": inv.pk, "print_url": reverse("invoice_print", args=[inv.pk])})


# ---------------- invoice number helpers ----------------
def _last_invoice(current=None, doc_type=None):
    """The most recently created bill of a type (other than the one being edited), for the hint under the number field."""
    qs = Invoice.objects.filter(invoice_no__isnull=False).order_by("-id")  # drafts have no number
    if doc_type:
        qs = qs.filter(doc_type=doc_type)
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
def _form_items(invoice):
    return [
        {"description": i.description, "hsn": i.hsn, "qty": _plain(i.qty), "unit": i.unit,
         "rate": _plain(i.rate), "amount": _plain(i.line_total),
         "discount_pct": _plain(i.discount_pct), "gst_rate": _plain(i.gst_rate)}
        for i in invoice.items.all()
    ]


def _party_fields(invoice):
    return {
        "party_name": invoice.party_name, "party_address": invoice.party_address, "party_gstin": invoice.party_gstin,
        "party_state": invoice.party_state, "party_phone": invoice.party_phone, "party_email": invoice.party_email,
        "place_of_supply": invoice.place_of_supply,
    }


def _prefill(source, target_type, firm, today):
    """Form data for a NEW bill that starts as a copy of an existing one: a repeat bill, an estimate turned into a tax
    invoice, or a credit note against an invoice. Nothing is saved until the person presses Save."""
    items, price_mode, notice = _form_items(source), source.price_mode, ""
    if target_type in GST_DOC_TYPES and source.doc_type not in GST_DOC_TYPES:
        # an estimate or bill of supply has no GST: the same prices become GST-excluded rates and GST is added on top
        price_mode = "EXCL"
        for it in items:
            it["gst_rate"] = _plain(settings.DEFAULT_GST_RATE)
        notice = "GST has been added on top of the prices. Check the GST rate of every line before saving."
    elif target_type == "CN":
        notice = f"Credit note against {source.invoice_no or 'this bill'}. Keep only the items and quantities being returned or corrected."
    return {
        "invoice_no": Invoice.next_number(doc_prefix(firm, target_type), today),
        "date": today.isoformat(), "price_mode": price_mode, "doc_type": target_type,
        **_party_fields(source),
        "ref_no": (source.invoice_no or "") if target_type == "CN" else "",
        "ref_date": source.date.isoformat() if target_type == "CN" else "",
        "notes": source.notes if target_type != "CN" else "", "notice": notice,
        "pending": False, "issued": False, "items": items,
    }


@login_required
def invoice_form(request, pk=None):
    firm = Firm.get()
    invoice = get_object_or_404(Invoice.objects.prefetch_related("items"), pk=pk) if pk else None
    if invoice is not None and invoice.is_cancelled:
        messages.error(request, "A cancelled bill cannot be edited.")
        return redirect("invoice_print", pk=invoice.pk)
    today = timezone.localdate()

    if invoice:
        inv = {
            "invoice_no": invoice.invoice_no or "",
            "date": invoice.date.isoformat(),
            "price_mode": invoice.price_mode,
            "doc_type": invoice.doc_type,
            **_party_fields(invoice),
            "ref_no": invoice.ref_no,
            "ref_date": invoice.ref_date.isoformat() if invoice.ref_date else "",
            "notes": invoice.notes,
            "notice": "",
            "pending": invoice.is_draft,
            "issued": not invoice.is_draft,
            "items": _form_items(invoice),
        }
    elif request.GET.get("copy", "").isdigit():
        source = get_object_or_404(Invoice.objects.prefetch_related("items"), pk=int(request.GET["copy"]))
        target = _doc_type(request.GET.get("as") or source.doc_type)
        inv = _prefill(source, target, firm, today)
    else:
        inv = {
            "invoice_no": Invoice.next_number(firm.invoice_prefix, today),
            "date": today.isoformat(),
            "price_mode": "AMT",
            "doc_type": "TAX",
            "party_name": "", "party_address": "", "party_gstin": "", "party_state": "",
            "party_phone": "", "party_email": "", "place_of_supply": "", "ref_no": "", "ref_date": "", "notice": "",
            "notes": "", "pending": False, "issued": False, "items": [],
        }

    init = {
        "save_url": reverse("invoice_update", args=[invoice.pk]) if invoice else reverse("invoice_save"),
        "calc_url": reverse("calc_api"),
        "new_url": reverse("invoice_new"),
        "check_url": reverse("check_number"),
        "invoice_id": invoice.pk if invoice else None,
        "next_numbers": {code: Invoice.next_number(doc_prefix(firm, code), timezone.localdate()) for code, _ in DOC_TYPES},
        "doc_types": [{"value": code, "label": label} for code, label in DOC_TYPES],
        "today": timezone.localdate().isoformat(),
        "last_invoices": {code: _last_invoice(invoice, code) for code, _ in DOC_TYPES},
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


LIST_PAGE_SIZE = 50


def _date_param(value):
    try:
        return datetime.date.fromisoformat((value or "").strip())
    except ValueError:
        return None


@login_required
def invoice_list(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    status = status if status in ("pending", "submitted", "cancelled") else ""
    kind = request.GET.get("type", "")
    kind = kind if kind in dict(DOC_TYPES) else ""
    date_from, date_to = _date_param(request.GET.get("from")), _date_param(request.GET.get("to"))
    qs = Invoice.objects.all()
    if q:
        qs = qs.filter(Q(invoice_no__icontains=q) | Q(party_name__icontains=q) | Q(party_gstin__icontains=q))
    if kind:
        qs = qs.filter(doc_type=kind)
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    if status == "pending":
        qs = qs.filter(submitted_on__isnull=True)
    elif status == "submitted":
        qs = qs.filter(submitted_on__isnull=False, status="ACTIVE")
    elif status == "cancelled":
        qs = qs.filter(status="CANCELLED")
    pending_count = Invoice.objects.filter(submitted_on__isnull=True).count()
    cancelled_count = Invoice.objects.filter(status="CANCELLED").count()
    total_count = Invoice.objects.count()
    counts = {"all": total_count, "pending": pending_count, "cancelled": cancelled_count,
              "submitted": total_count - pending_count - cancelled_count}
    # the filters are kept in every tab and page link (the page number and, for tabs, the status are left out)
    keep = {k: v for k, v in (("q", q), ("type", kind), ("from", date_from.isoformat() if date_from else ""),
                              ("to", date_to.isoformat() if date_to else "")) if v}
    page = Paginator(qs, LIST_PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "billing/invoice_list.html",
        {"invoices": page, "pg": page, "q": q, "status": status, "counts": counts, "kind": kind,
         "date_from": date_from.isoformat() if date_from else "", "date_to": date_to.isoformat() if date_to else "",
         "doc_types": DOC_TYPES, "keep_qs": urlencode(keep),
         "page_qs": urlencode({**keep, **({"status": status} if status else {})}),
         "filtered": bool(keep)},
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
                    invoice.invoice_no = Invoice.next_number(doc_prefix(firm, invoice.doc_type), invoice.date)
                    invoice.submitted_on = today
                    invoice.save()
                audit.record(request, "Submitted", invoice.invoice_no, f"{invoice.party_name}, total {invoice.total}")
                break
            except IntegrityError:  # another bill took this number a moment ago: try the next one
                invoice.invoice_no = None
                invoice.submitted_on = None
    target = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        target = reverse("invoice_list")
    return HttpResponseRedirect(target)


@login_required
@require_POST
def invoice_cancel(request, pk):
    """Cancel a numbered bill. It stays in the number series (marked CANCELLED) and is left out of the sales figures."""
    invoice = get_object_or_404(Invoice, pk=pk)
    if not request.user.has_perm("billing.cancel_invoice"):
        return HttpResponseForbidden("You do not have permission to cancel invoices.")
    reason = (request.POST.get("reason") or "").strip()
    if invoice.invoice_no is None:
        messages.error(request, "This bill has no number yet, so there is nothing to cancel. Delete the draft instead.")
    elif invoice.is_cancelled:
        messages.info(request, "This bill is already cancelled.")
    elif not reason:
        messages.error(request, "Enter the reason for cancelling the bill.")
    else:
        invoice.status = "CANCELLED"
        invoice.cancelled_on = timezone.localdate()
        invoice.cancel_reason = reason[:200]
        invoice.save()
        audit.record(request, "Cancelled", invoice.invoice_no, f"{invoice.party_name}, total {invoice.total}. Reason: {invoice.cancel_reason}")
        messages.success(request, f"{invoice.invoice_no} is cancelled. Its number stays in the series.")
    return redirect("invoice_print", pk=invoice.pk)


@login_required
@require_POST
def invoice_delete_draft(request, pk):
    """Only a draft (no number) can be deleted. A numbered bill must be cancelled instead."""
    invoice = get_object_or_404(Invoice, pk=pk)
    if invoice.invoice_no is not None:
        messages.error(request, "A bill with a number cannot be deleted. Cancel it instead.")
        return redirect("invoice_print", pk=invoice.pk)
    audit.record(request, "Deleted draft", "", f"{invoice.get_doc_type_display()}, {invoice.party_name}, total {invoice.total}")
    invoice.delete()
    messages.success(request, "The draft has been deleted.")
    return redirect("invoice_list")


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
            "is_tax": invoice.charges_gst,
            "doc_title": {"TAX": "Tax invoice", "SUPPLY": "Bill of supply", "EST": "Estimate", "CN": "Credit note"}[invoice.doc_type],
            "number_label": {"TAX": "Invoice no.", "SUPPLY": "Bill no.", "EST": "Estimate no.", "CN": "Credit note no."}[invoice.doc_type],
            "can_cancel": request.user.has_perm("billing.cancel_invoice"),
            "upi_qr": _upi_qr(invoice, firm),
            "share": _share_links(invoice, firm),
        },
    )


def _upi_qr(invoice, firm):
    """Payment QR (inline SVG) for bills that ask for money: not for drafts, cancelled bills, estimates or credit notes."""
    if not firm.upi_id or not invoice.invoice_no or invoice.is_cancelled or invoice.doc_type not in ("TAX", "SUPPLY") or invoice.total <= 0:
        return ""
    return share.qr_svg(share.upi_uri(firm.upi_id, firm.name, invoice.total, invoice.invoice_no))


def _share_links(invoice, firm):
    """WhatsApp / e-mail links with a ready message. The PDF itself is attached by the person (Print -> Save as PDF)."""
    if not invoice.invoice_no or invoice.is_cancelled:
        return None
    title = {"TAX": "Invoice", "SUPPLY": "Bill of supply", "EST": "Estimate", "CN": "Credit note"}[invoice.doc_type]
    text = (f"Dear {invoice.party_name},\n{title} {invoice.invoice_no} dated {invoice.date:%d-%m-%Y} for Rs. {invoice.total} "
            f"is attached.\nThank you,\n{firm.name}")
    return {"whatsapp": share.whatsapp_url(invoice.party_phone, text),
            "email": share.mailto_url(invoice.party_email, f"{title} {invoice.invoice_no} from {firm.name}", text)}


@login_required
def firm_image(request, kind):
    """Shows the firm's logo or signature (only to logged-in users)."""
    from django.http import FileResponse, Http404
    if kind not in ("logo", "signature"):
        raise Http404
    field = getattr(Firm.get(), kind)
    if not field:
        raise Http404
    try:
        handle = field.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404
    ctype = "image/png" if field.name.lower().endswith(".png") else "image/jpeg"
    response = FileResponse(handle, content_type=ctype)
    response["Cache-Control"] = "private, max-age=300"
    return response


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
    issued = Invoice.objects.filter(
        invoice_no__isnull=False, date__gte=begin, date__lte=end, status="ACTIVE"
    ).exclude(doc_type="EST")  # estimates are not sales, cancelled bills are not counted
    invoices = list(issued.values("date", "party_name", "party_gstin", "doc_type", "is_intra_state", "taxable_value", "cgst", "sgst", "igst", "round_off", "total"))
    items = list(
        InvoiceItem.objects.filter(invoice__in=issued).values("gst_rate", "taxable", "gst_amount", doc_type=F("invoice__doc_type"))
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


# ---------------- GST return data, series check, party statement ----------------

def _period(request):
    """(financial year start, first day, last day, month text) from ?fy=2026 and an optional ?month=2026-10."""
    today = timezone.localdate()
    try:
        start = int(request.GET.get("fy", ""))
        if not 2000 <= start <= 2100:
            raise ValueError
    except ValueError:
        start = fy_start_year(today)
    begin, end, month = datetime.date(start, 4, 1), datetime.date(start + 1, 3, 31), ""
    m = re.fullmatch(r"(\d{4})-(\d{2})", request.GET.get("month", ""))
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and begin <= datetime.date(y, mo, 1) <= end:
            month = f"{y}-{mo:02d}"
            begin = datetime.date(y, mo, 1)
            end = (datetime.date(y + (mo == 12), mo % 12 + 1, 1)) - datetime.timedelta(days=1)
    return start, begin, end, month


def _return_data(begin, end):
    """Active, numbered tax invoices / bills of supply / credit notes of the period, with their lines."""
    qs = Invoice.objects.filter(invoice_no__isnull=False, date__gte=begin, date__lte=end, status="ACTIVE").exclude(doc_type="EST")
    invoices = list(qs.values("id", "invoice_no", "date", "doc_type", "party_name", "party_gstin", "place_of_supply",
                              "is_intra_state", "total", "ref_no", "ref_date"))
    items = list(InvoiceItem.objects.filter(invoice__in=qs).values("invoice_id", "hsn", "unit", "qty", "gst_rate", "taxable", "gst_amount"))
    return invoices, items


def _csv_response(name, header, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{name}.csv"'
    response.write("\ufeff")
    w = csv.writer(response)
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    return response


@login_required
def gst_reports(request):
    start, begin, end, month = _period(request)
    # the series check always looks at the whole financial year: a gap is a gap whatever month is chosen
    docs = Invoice.objects.filter(invoice_no__isnull=False, date__gte=datetime.date(start, 4, 1),
                                  date__lte=datetime.date(start + 1, 3, 31)).values("invoice_no", "doc_type", "status")
    series = series_summary(list(docs))
    invoices, items = _return_data(begin, end)
    b2b, b2c, hsn = b2b_rows(invoices, items), b2c_rows(invoices, items), hsn_rows(invoices, items)
    months = [{"value": f"{y}-{m:02d}", "label": f"{MONTH_LABELS[m - 1]} {y}"} for y, m in fy_months(start)]
    return render(request, "billing/gst_reports.html", {
        "series": series, "b2b_count": len(b2b), "b2c_count": len(b2c), "hsn_count": len(hsn),
        "fy": start, "fy_label": fy_label(start), "month": month, "months": months,
        "fy_options": [{"value": y, "label": fy_label(y)} for y in range(fy_start_year(timezone.localdate()) + 1, fy_start_year(timezone.localdate()) - 6, -1)],
        "has_gap": any(r["missing"] for r in series),
    })


@login_required
def gst_export(request, kind):
    start, begin, end, month = _period(request)
    tag = f"FY{fy_label(start)}" + (f"-{month}" if month else "")
    invoices, items = _return_data(begin, end)
    if kind == "b2b":
        rows = [[r["gstin"], r["party"], r["note_type"], r["invoice_no"], r["date"].strftime("%d-%m-%Y"), r["ref_no"], r["invoice_value"],
                 r["place_of_supply"], r["rate"], r["taxable"], r["igst"], r["cgst"], r["sgst"]] for r in b2b_rows(invoices, items)]
        return _csv_response(f"GSTR1-B2B-{tag}", ["GSTIN of buyer", "Buyer name", "Document", "Number", "Date", "Against invoice", "Document value",
                                                 "Place of supply", "GST rate %", "Taxable value", "IGST", "CGST", "SGST"], rows)
    if kind == "b2c":
        rows = [[r["place_of_supply"], r["rate"], r["taxable"], r["igst"], r["cgst"], r["sgst"]] for r in b2c_rows(invoices, items)]
        return _csv_response(f"GSTR1-B2C-{tag}", ["Place of supply", "GST rate %", "Taxable value (net of credit notes)", "IGST", "CGST", "SGST"], rows)
    if kind == "hsn":
        rows = [[r["hsn"], r["unit"], r["qty"], r["rate"], r["value"], r["taxable"], r["igst"], r["cgst"], r["sgst"]] for r in hsn_rows(invoices, items)]
        return _csv_response(f"GSTR1-HSN-{tag}", ["HSN", "Unit", "Quantity", "GST rate %", "Total value", "Taxable value", "IGST", "CGST", "SGST"], rows)
    if kind == "series":
        docs = Invoice.objects.filter(invoice_no__isnull=False, date__gte=datetime.date(start, 4, 1),
                                      date__lte=datetime.date(start + 1, 3, 31)).values("invoice_no", "doc_type", "status")
        rows = [[r["label"], r["series"], r["first"], r["last"], r["count"], r["cancelled_count"], ", ".join(r["cancelled"]), ", ".join(r["missing"])]
                for r in series_summary(list(docs))]
        return _csv_response(f"Documents-issued-FY{fy_label(start)}", ["Document", "Series", "From", "To", "Issued", "Cancelled", "Cancelled numbers", "Missing numbers"], rows)
    return HttpResponse("Unknown report.", status=404)


@login_required
def party_statement(request):
    """All bills of one party in a financial year with a running total (bills only; payments are not tracked here)."""
    start, begin, end, month = _period(request)
    begin, end = datetime.date(start, 4, 1), datetime.date(start + 1, 3, 31)
    names = list(Invoice.objects.filter(invoice_no__isnull=False).exclude(doc_type="EST").order_by("party_name")
                 .values_list("party_name", flat=True).distinct())
    name = request.GET.get("party", "").strip()
    rows, running, total = [], Decimal("0.00"), None
    if name:
        for inv in Invoice.objects.filter(invoice_no__isnull=False, party_name__iexact=name, status="ACTIVE", date__gte=begin, date__lte=end) \
                .exclude(doc_type="EST").order_by("date", "id"):
            amount = -inv.total if inv.doc_type == "CN" else inv.total
            running += amount
            rows.append({"inv": inv, "amount": amount, "running": running})
        total = running
        if request.GET.get("csv"):
            return _csv_response(f"Statement-{re.sub(r'[^A-Za-z0-9]+', '_', name)}-FY{fy_label(start)}",
                                 ["Date", "Document", "Number", "Amount", "Running total"],
                                 [[r["inv"].date.strftime("%d-%m-%Y"), r["inv"].get_doc_type_display(), r["inv"].invoice_no, r["amount"], r["running"]] for r in rows])
    return render(request, "billing/party_statement.html", {
        "names": sorted({n.strip() for n in names if n and n.strip()}, key=str.lower), "name": name, "rows": rows, "total": total,
        "fy": start, "fy_label": fy_label(start),
        "fy_options": [{"value": y, "label": fy_label(y)} for y in range(fy_start_year(timezone.localdate()) + 1, fy_start_year(timezone.localdate()) - 6, -1)],
    })


@login_required
def backup_download(request):
    """A fresh, consistent copy of the database for superusers (for the office computer's own backup routine)."""
    from django.http import FileResponse
    import tempfile
    from .backup import snapshot
    db = settings.DATABASES["default"]
    if not request.user.is_superuser:
        return HttpResponseForbidden("Only a superuser can download a backup.")
    if not db["ENGINE"].endswith("sqlite3"):
        return HttpResponseForbidden("Backups are only built in for SQLite.")
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    tmp.close()
    snapshot(db["NAME"], tmp.name)
    audit.record(request, "Downloaded backup")
    stamp = timezone.localtime().strftime("%Y-%m-%d-%H%M")
    return FileResponse(open(tmp.name, "rb"), as_attachment=True, filename=f"billing-backup-{stamp}.sqlite3")
