import datetime
import json
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .calc import D, amount_in_words, compute_invoice
from .models import STATE_CODES, Firm, Invoice, InvoiceItem, Party, Product

MAX_ROWS = 500
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


def _is_intra(firm, place_of_supply):
    place = (place_of_supply or "").strip()
    return place == "" or place == firm.state


def _serialize(result):
    out = {k: _money(result[k]) for k in ("taxable", "cgst", "sgst", "igst", "gst_total", "round_off", "total")}
    out["words"] = result["words"]
    out["intra"] = result["intra"]
    out["lines"] = [{k: _money(v) for k, v in line.items()} for line in result["lines"]]
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
        result = compute_invoice(
            items,
            inclusive=data.get("price_mode") == "INCL",
            intra=_is_intra(firm, data.get("place_of_supply")),
        )
    except ArithmeticError:
        return _err(["One of the amounts is too large."])
    return JsonResponse({"ok": True, **_serialize(result)})


# ---------------- validation of an invoice ----------------
def _clean_payload(data, firm):
    errors = []

    invoice_no = (data.get("invoice_no") or "").strip()
    if not invoice_no:
        errors.append("Enter an invoice number.")
    elif len(invoice_no) > 40:
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

    party_state = (data.get("party_state") or "").strip()
    if party_state and party_state not in STATE_CODES:
        errors.append("Select a valid party state.")
    place = (data.get("place_of_supply") or "").strip() or party_state or firm.state
    if place not in STATE_CODES:
        errors.append("Select a valid place of supply.")

    price_mode = "INCL" if data.get("price_mode") == "INCL" else "EXCL"

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
        if not desc and not qty_text and not rate_text:
            continue  # skip empty lines
        label = f"Line {n}"
        qty, rate = D(qty_text), D(rate_text)
        disc, gst = D(r.get("discount_pct")), D(r.get("gst_rate"))
        hsn, unit = str(r.get("hsn") or "").strip(), str(r.get("unit") or "").strip()

        if not desc:
            errors.append(f"{label}: enter the item name.")
        elif len(desc) > 300:
            errors.append(f"{label}: the item name is too long.")
        if qty <= 0 or qty >= Decimal(10) ** 10:
            errors.append(f"{label}: quantity must be greater than 0.")
        elif not _decimals_ok(qty, 3):
            errors.append(f"{label}: quantity can have at most 3 decimal places.")
        if rate_text == "":
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
            {"description": desc, "hsn": hsn, "qty": qty, "unit": unit, "rate": rate,
             "discount_pct": disc, "gst_rate": gst}
        )

    if not items and not errors:
        errors.append("Add at least one item.")
    if errors:
        return None, errors

    try:
        result = compute_invoice(items, inclusive=price_mode == "INCL", intra=_is_intra(firm, place))
    except ArithmeticError:
        return None, ["One of the amounts is too large."]
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
            state=c["party_state"], phone=c["party_phone"],
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
    dup = Invoice.objects.filter(invoice_no=c["invoice_no"])
    if invoice:
        dup = dup.exclude(pk=invoice.pk)
    dup_msg = [f"Invoice number {c['invoice_no']} already exists. Enter a different number."]
    if dup.exists():
        return _err(dup_msg)

    r = c["result"]
    try:
        with transaction.atomic():
            inv = invoice or Invoice()
            inv.invoice_no = c["invoice_no"]
            inv.date = c["date"]
            inv.party = _resolve_party(c)
            inv.party_name = c["party_name"]
            inv.party_address = c["party_address"]
            inv.party_gstin = c["party_gstin"]
            inv.party_state = c["party_state"]
            inv.party_phone = c["party_phone"]
            inv.place_of_supply = c["place_of_supply"]
            inv.price_mode = c["price_mode"]
            inv.is_intra_state = r["intra"]
            inv.taxable_value = r["taxable"]
            inv.cgst, inv.sgst, inv.igst = r["cgst"], r["sgst"], r["igst"]
            inv.round_off = r["round_off"]
            inv.total = r["total"]
            inv.notes = c["notes"]
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
    except IntegrityError:
        return _err(dup_msg)

    return JsonResponse({"ok": True, "id": inv.pk, "print_url": reverse("invoice_print", args=[inv.pk])})


# ---------------- pages ----------------
@login_required
def invoice_form(request, pk=None):
    firm = Firm.get()
    invoice = get_object_or_404(Invoice.objects.prefetch_related("items"), pk=pk) if pk else None

    if invoice:
        inv = {
            "invoice_no": invoice.invoice_no,
            "date": invoice.date.isoformat(),
            "price_mode": invoice.price_mode,
            "party_name": invoice.party_name,
            "party_address": invoice.party_address,
            "party_gstin": invoice.party_gstin,
            "party_state": invoice.party_state,
            "party_phone": invoice.party_phone,
            "place_of_supply": invoice.place_of_supply,
            "notes": invoice.notes,
            "items": [
                {"description": i.description, "hsn": i.hsn, "qty": _plain(i.qty), "unit": i.unit,
                 "rate": _plain(i.rate), "discount_pct": _plain(i.discount_pct), "gst_rate": _plain(i.gst_rate)}
                for i in invoice.items.all()
            ],
        }
    else:
        today = timezone.localdate()
        inv = {
            "invoice_no": Invoice.next_number(firm.invoice_prefix, today),
            "date": today.isoformat(),
            "price_mode": "EXCL",
            "party_name": "", "party_address": "", "party_gstin": "", "party_state": "",
            "party_phone": "", "place_of_supply": "", "notes": "", "items": [],
        }

    init = {
        "save_url": reverse("invoice_update", args=[invoice.pk]) if invoice else reverse("invoice_save"),
        "calc_url": reverse("calc_api"),
        "new_url": reverse("invoice_new"),
        "firm_state": firm.state,
        "state_codes": STATE_CODES,
        "gst_rates": [_plain(r) for r in settings.GST_RATES],
        "default_gst": _plain(settings.DEFAULT_GST_RATE),
        "parties": list(Party.objects.values("id", "name", "address", "gstin", "state", "phone")),
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
    qs = Invoice.objects.all()
    if q:
        qs = qs.filter(Q(invoice_no__icontains=q) | Q(party_name__icontains=q) | Q(party_gstin__icontains=q))
    return render(request, "billing/invoice_list.html", {"invoices": qs[:200], "q": q})


@login_required
def invoice_print(request, pk):
    invoice = get_object_or_404(Invoice.objects.prefetch_related("items"), pk=pk)
    firm = Firm.get()
    return render(
        request,
        "billing/invoice_print.html",
        {
            "invoice": invoice,
            "items": invoice.items.all(),
            "firm": firm,
            "firm_state_code": STATE_CODES.get(firm.state, ""),
            "pos_code": STATE_CODES.get(invoice.place_of_supply, ""),
            "words": amount_in_words(invoice.total),
            "inclusive": invoice.price_mode == "INCL",
        },
    )
