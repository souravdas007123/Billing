"""Sales summary for the dashboard. Pure functions (no database access) so the numbers are easy to test."""
import datetime
from decimal import Decimal

ZERO = Decimal("0.00")
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fy_start_year(d):
    """The financial year runs April to March: 12-Oct-2026 belongs to FY 2026-27."""
    return d.year if d.month >= 4 else d.year - 1


def fy_label(start_year):
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def fy_months(start_year):
    """The 12 (year, month) pairs of a financial year, April first."""
    return [(start_year if m >= 4 else start_year + 1, m) for m in (4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3)]


def _empty_month(year, month):
    return {
        "year": year, "month": month, "label": f"{MONTH_NAMES[month - 1]} {year}", "bills": 0,
        "taxable": ZERO, "cgst": ZERO, "sgst": ZERO, "igst": ZERO, "gst": ZERO, "round_off": ZERO, "total": ZERO,
    }


def build_report(invoices, items, start_year, today=None):
    """
    invoices: iterable of dicts (date, party_name, party_gstin, doc_type, is_intra_state, taxable_value, cgst, sgst, igst, round_off, total) of SUBMITTED bills.
    items:    iterable of dicts (gst_rate, taxable, gst_amount, optional doc_type) of the lines of those bills.
    Bills are counted in the month of their invoice date. Drafts are not part of any figure here.
    """
    today = today or datetime.date.today()
    months = [_empty_month(y, m) for y, m in fy_months(start_year)]
    index = {(m["year"], m["month"]): m for m in months}
    parties = {}
    credit = {"bills": 0, "taxable": ZERO, "total": ZERO}  # credit notes (already deducted from every figure)
    intra = {"bills": 0, "taxable": ZERO, "total": ZERO}
    inter = {"bills": 0, "taxable": ZERO, "total": ZERO}
    registered = {"bills": 0, "taxable": ZERO, "total": ZERO}    # party has a GSTIN (B2B)
    unregistered = {"bills": 0, "taxable": ZERO, "total": ZERO}  # party has no GSTIN (B2C)
    by_type = {"TAX": {"bills": 0, "taxable": ZERO, "total": ZERO}, "SUPPLY": {"bills": 0, "taxable": ZERO, "total": ZERO}}
    for inv in invoices:
        row = index.get((inv["date"].year, inv["date"].month))
        if row is None:
            continue
        sign = -1 if inv.get("doc_type") == "CN" else 1  # a credit note takes away from the sales
        if sign == 1:
            row["bills"] += 1
        for k_row, k_inv in (("taxable", "taxable_value"), ("cgst", "cgst"), ("sgst", "sgst"), ("igst", "igst"),
                             ("round_off", "round_off"), ("total", "total")):
            row[k_row] += sign * inv[k_inv]
        gst = sign * (inv["cgst"] + inv["sgst"] + inv["igst"])
        row["gst"] += gst
        key = (inv["party_name"] or "").strip().lower()
        p = parties.setdefault(key, {"name": (inv["party_name"] or "").strip(), "bills": 0, "total": ZERO})
        p["bills"] += 1 if sign == 1 else 0
        p["total"] += sign * inv["total"]
        buckets = [intra if inv["is_intra_state"] else inter, registered if (inv.get("party_gstin") or "").strip() else unregistered]
        if inv.get("doc_type", "TAX") in by_type:
            buckets.append(by_type[inv.get("doc_type", "TAX")])
        if sign == -1:
            credit["bills"] += 1
            credit["taxable"] += inv["taxable_value"]
            credit["total"] += inv["total"]
        for bucket in buckets:
            bucket["bills"] += 1 if sign == 1 else 0
            bucket["taxable"] += sign * inv["taxable_value"]
            bucket["total"] += sign * inv["total"]

    totals = _empty_month(start_year, 4)
    totals["label"] = "Total"
    for m in months:
        for k in ("bills", "taxable", "cgst", "sgst", "igst", "gst", "round_off", "total"):
            totals[k] += m[k]
    peak = max((m["total"] for m in months), default=ZERO)
    for m in months:
        m["is_future"] = (m["year"], m["month"]) > (today.year, today.month)
        m["bar_pct"] = float(m["total"] / peak * 100) if peak else 0.0

    rates = {}
    for it in items:
        sign = -1 if it.get("doc_type") == "CN" else 1
        r = rates.setdefault(it["gst_rate"], {"rate": it["gst_rate"], "taxable": ZERO, "gst": ZERO})
        r["taxable"] += sign * it["taxable"]
        r["gst"] += sign * it["gst_amount"]
    rate_rows = sorted(rates.values(), key=lambda r: r["rate"])

    top = sorted(parties.values(), key=lambda p: p["total"], reverse=True)[:5]
    grand = totals["total"]
    for p in top:
        p["share"] = float(p["total"] / grand * 100) if grand else 0.0
    best = max(months, key=lambda m: m["total"]) if grand else None
    return {
        "months": months, "totals": totals, "parties": top, "rates": rate_rows, "intra": intra, "inter": inter,
        "registered": registered, "unregistered": unregistered, "by_type": by_type, "credit": credit,
        "average_bill": (grand / totals["bills"]).quantize(Decimal("0.01")) if totals["bills"] else ZERO,
        "best_month": best["label"] if best else "",
    }


def inr(value, places=2):
    """Indian digit grouping: 1234567.5 -> '12,34,567.50'."""
    q = Decimal(1).scaleb(-places)
    v = Decimal(value or 0).quantize(q)
    sign = "-" if v < 0 else ""
    whole, _, frac = format(abs(v), "f").partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}{whole}" + (f".{frac}" if frac else "")
