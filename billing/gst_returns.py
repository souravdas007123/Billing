"""Data for the GST return (GSTR-1) and the series check. Pure functions (no database access), so they are easy to test.

Everything is built from the lines of each bill, with the same CGST = SGST rule as the invoice itself.
"""
import re
from decimal import Decimal

from .calc import split_gst

ZERO = Decimal("0.00")
TYPE_LABELS = {"TAX": "Tax invoice", "SUPPLY": "Bill of supply", "CN": "Credit note", "EST": "Estimate"}
TYPE_ORDER = ["TAX", "CN", "SUPPLY", "EST"]


def _split_no(invoice_no):
    """'INV/26-27/0007' -> ('INV/26-27/', 7, 4). None when the number does not end in digits."""
    m = re.search(r"(\d+)$", invoice_no or "")
    if not m:
        return None
    return invoice_no[: m.start()], int(m.group(1)), len(m.group(1))


def series_summary(docs):
    """
    docs: dicts (invoice_no, doc_type, status). Numbered bills only.
    One row per number series: first, last, how many, how many cancelled and the numbers that are missing in between
    (a missing number in a GST series must be explained to the department).
    """
    groups = {}
    for d in docs:
        parts = _split_no(d.get("invoice_no"))
        if parts is None:
            continue
        prefix, num, width = parts
        g = groups.setdefault((d["doc_type"], prefix), {"nums": set(), "cancelled": [], "width": width, "numbers": {}})
        g["nums"].add(num)
        g["numbers"][num] = d["invoice_no"]
        if d.get("status") == "CANCELLED":
            g["cancelled"].append(d["invoice_no"])
    rows = []
    for (doc_type, prefix), g in groups.items():
        lo, hi = min(g["nums"]), max(g["nums"])
        missing = [f"{prefix}{n:0{g['width']}d}" for n in range(lo, hi + 1) if n not in g["nums"]]
        rows.append({
            "doc_type": doc_type, "label": TYPE_LABELS.get(doc_type, doc_type), "series": prefix.rstrip("/"),
            "first": g["numbers"][lo], "last": g["numbers"][hi], "count": len(g["nums"]),
            "cancelled": sorted(g["cancelled"]), "cancelled_count": len(g["cancelled"]), "missing": missing,
        })
    rows.sort(key=lambda r: (TYPE_ORDER.index(r["doc_type"]) if r["doc_type"] in TYPE_ORDER else 9, r["series"]))
    return rows


def _line_tax(line, intra):
    cgst, sgst, igst = split_gst(line["gst_amount"], intra)
    return cgst, sgst, igst


def b2b_rows(invoices, items):
    """
    GSTR-1 table 4 (B2B) and 9B (credit notes) for registered buyers, one row per invoice and GST rate.
    invoices: dicts (id, invoice_no, date, doc_type, party_name, party_gstin, place_of_supply, is_intra_state, total, ref_no, ref_date)
    of tax invoices and credit notes. items: dicts (invoice_id, gst_rate, taxable, gst_amount).
    """
    by_inv = {}
    for it in items:
        by_inv.setdefault(it["invoice_id"], []).append(it)
    rows = []
    for inv in sorted(invoices, key=lambda i: (i["date"], i["invoice_no"])):
        if inv["doc_type"] not in ("TAX", "CN") or not (inv.get("party_gstin") or "").strip():
            continue
        rates = {}
        for it in by_inv.get(inv["id"], []):
            r = rates.setdefault(it["gst_rate"], [ZERO, ZERO, ZERO, ZERO])
            cgst, sgst, igst = _line_tax(it, inv["is_intra_state"])
            r[0] += it["taxable"]; r[1] += cgst; r[2] += sgst; r[3] += igst
        for rate in sorted(rates):
            taxable, cgst, sgst, igst = rates[rate]
            rows.append({
                "gstin": inv["party_gstin"].strip().upper(), "party": inv["party_name"],
                "note_type": "Credit note" if inv["doc_type"] == "CN" else "Invoice",
                "invoice_no": inv["invoice_no"], "date": inv["date"], "ref_no": inv.get("ref_no", ""),
                "invoice_value": inv["total"], "place_of_supply": inv.get("place_of_supply") or "",
                "rate": rate, "taxable": taxable, "igst": igst, "cgst": cgst, "sgst": sgst,
            })
    return rows


def b2c_rows(invoices, items):
    """
    GSTR-1 table 7 (B2C small): sales to buyers without a GSTIN, added up by place of supply and GST rate.
    Credit notes are subtracted.
    """
    by_inv = {}
    for it in items:
        by_inv.setdefault(it["invoice_id"], []).append(it)
    table = {}
    for inv in invoices:
        if inv["doc_type"] not in ("TAX", "CN") or (inv.get("party_gstin") or "").strip():
            continue
        sign = -1 if inv["doc_type"] == "CN" else 1
        for it in by_inv.get(inv["id"], []):
            cgst, sgst, igst = _line_tax(it, inv["is_intra_state"])
            key = (inv.get("place_of_supply") or "", it["gst_rate"])
            r = table.setdefault(key, [ZERO, ZERO, ZERO, ZERO])
            r[0] += sign * it["taxable"]; r[1] += sign * igst; r[2] += sign * cgst; r[3] += sign * sgst
    return [
        {"place_of_supply": pos, "rate": rate, "taxable": v[0], "igst": v[1], "cgst": v[2], "sgst": v[3]}
        for (pos, rate), v in sorted(table.items(), key=lambda kv: (kv[0][0], kv[0][1]))
    ]


def hsn_rows(invoices, items):
    """GSTR-1 table 12: HSN-wise summary of outward supplies (tax invoices, bills of supply; credit notes subtracted)."""
    inv_by_id = {i["id"]: i for i in invoices}
    table = {}
    for it in items:
        inv = inv_by_id.get(it["invoice_id"])
        if inv is None or inv["doc_type"] == "EST":
            continue
        sign = -1 if inv["doc_type"] == "CN" else 1
        cgst, sgst, igst = _line_tax(it, inv["is_intra_state"])
        key = ((it.get("hsn") or "").strip() or "(blank)", (it.get("unit") or "").strip(), it["gst_rate"])
        r = table.setdefault(key, {"qty": Decimal("0"), "taxable": ZERO, "igst": ZERO, "cgst": ZERO, "sgst": ZERO, "value": ZERO})
        r["qty"] += sign * it["qty"]; r["taxable"] += sign * it["taxable"]
        r["igst"] += sign * igst; r["cgst"] += sign * cgst; r["sgst"] += sign * sgst
        r["value"] += sign * (it["taxable"] + it["gst_amount"])
    return [
        {"hsn": k[0], "unit": k[1], "rate": k[2], **v}
        for k, v in sorted(table.items(), key=lambda kv: (kv[0][0], kv[0][2], kv[0][1]))
    ]
