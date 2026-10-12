"""All invoice calculations live here (independent of Django, so they are easy to test).

Rules:
- Everything uses Decimal; floats are never used.
- Exclusive: taxable = qty*rate - discount; GST is added on top.
- Inclusive: line total = qty*rate - discount (the final amount); taxable = total*100/(100+gst%).
- GST is rounded per line; CGST = GST/2 (rounded) and SGST = GST - CGST, so the two always add up to the GST.
- The invoice total is rounded to the nearest rupee, and the round-off is shown as a separate line.
- Amount-entry mode: the user types each line's final amount (GST included). The taxable value and GST are
  taken out of that amount, and the rate is derived as taxable value / quantity.
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

TWO = Decimal("0.01")
HUNDRED = Decimal("100")


def D(value, default="0"):
    """Safely convert any input (str/number/None) to Decimal. Strips commas, currency symbols and %."""
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    text = str(value).replace(",", "").replace("₹", "").replace("%", "").strip()
    if text == "":
        return Decimal(default)
    try:
        result = Decimal(text)
    except InvalidOperation:
        return Decimal(default)
    return result if result.is_finite() else Decimal(default)


def q2(value):
    return value.quantize(TWO, rounding=ROUND_HALF_UP)


def compute_line(qty, rate, discount_pct, gst_rate, inclusive, intra):
    """One line. Same-state bills split the GST into two EQUAL halves (CGST = SGST, to the paisa):
    the half is rounded first, and the line's taxable value absorbs any odd paisa when the amount includes GST."""
    qty, rate, discount_pct, gst_rate = D(qty), D(rate), D(discount_pct), D(gst_rate)
    net = qty * rate * (HUNDRED - discount_pct) / HUNDRED
    if inclusive:
        total = q2(net)
        if intra:
            gst = 2 * q2(total * gst_rate / (2 * (HUNDRED + gst_rate)))
            taxable = total - gst
        else:
            taxable = q2(total * HUNDRED / (HUNDRED + gst_rate))
            gst = total - taxable
    else:
        taxable = q2(net)
        gst = 2 * q2(taxable * gst_rate / (2 * HUNDRED)) if intra else q2(taxable * gst_rate / HUNDRED)
        total = taxable + gst
    cgst, sgst, igst = split_gst(gst, intra)
    return {
        "taxable": taxable,
        "gst": gst,
        "cgst": cgst,
        "sgst": sgst,
        "igst": igst,
        "total": total,
    }


def split_gst(gst, intra):
    """One line's GST as (CGST, SGST, IGST). Same state: two equal halves (a bill saved before this rule can have an odd paisa; CGST gets the extra one)."""
    if intra:
        cgst = q2(gst / 2)
        return cgst, gst - cgst, Decimal("0.00")
    return Decimal("0.00"), Decimal("0.00"), gst


def rate_summary(entries):
    """Tax summary by GST rate. entries: (gst_rate, line) pairs, where line has taxable, gst, cgst, sgst, igst.

    Built from the per-line figures, so every column adds up to the invoice totals. Empty lines are skipped.
    """
    rates = {}
    for rate, line in entries:
        if not (line["taxable"] or line["gst"]):
            continue
        r = rates.setdefault(
            D(rate).normalize(), {k: Decimal("0.00") for k in ("taxable", "gst", "cgst", "sgst", "igst")}
        )
        for k in r:
            r[k] += line[k]
    return [{"rate": rate, **vals} for rate, vals in sorted(rates.items())]


FOUR = Decimal("0.0001")


def compute_line_from_amount(qty, amount, gst_rate, intra):
    """Amount-entry mode: `amount` is the line's final total, GST included.

    The line total always equals the amount typed. The rate is derived (taxable value / quantity),
    and a blank or zero quantity is treated as 1.
    """
    qty = D(qty)
    if qty <= 0:
        qty = Decimal(1)
    line = compute_line(1, amount, 0, gst_rate, True, intra)
    line["rate"] = (line["taxable"] / qty).quantize(FOUR, rounding=ROUND_HALF_UP)
    return line


def compute_invoice(items, inclusive, intra, amount_mode=False):
    """items: list of dicts (qty, rate, discount_pct, gst_rate; or qty, amount, gst_rate in amount mode).

    Blank lines produce zeros.
    """
    if amount_mode:
        lines = [
            compute_line_from_amount(it.get("qty"), it.get("amount"), it.get("gst_rate"), intra) for it in items
        ]
    else:
        lines = [
            compute_line(
                it.get("qty"), it.get("rate"), it.get("discount_pct"), it.get("gst_rate"), inclusive, intra
            )
            for it in items
        ]
    zero = Decimal("0.00")
    summary = rate_summary((it.get("gst_rate"), line) for it, line in zip(items, lines))
    taxable = sum((l["taxable"] for l in lines), zero)
    cgst = sum((l["cgst"] for l in lines), zero)
    sgst = sum((l["sgst"] for l in lines), zero)
    igst = sum((l["igst"] for l in lines), zero)
    gst_total = cgst + sgst + igst
    exact_total = taxable + gst_total
    total = exact_total.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return {
        "lines": lines,
        "summary": summary,
        "taxable": taxable,
        "cgst": cgst,
        "sgst": sgst,
        "igst": igst,
        "gst_total": gst_total,
        "round_off": total - exact_total,
        "total": total,
        "words": amount_in_words(total),
        "intra": intra,
    }


# ---------- Amount in words (Indian system) ----------
_ONES = [
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
    "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen",
]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _below_thousand(n):
    parts = []
    if n >= 100:
        parts.append(_ONES[n // 100] + " Hundred")
        n %= 100
    if n >= 20:
        parts.append(_TENS[n // 10] + ((" " + _ONES[n % 10]) if n % 10 else ""))
    elif n > 0:
        parts.append(_ONES[n])
    return " ".join(parts)


def _int_to_words(n):
    if n == 0:
        return "Zero"
    parts = []
    for divisor, name in ((10_000_000, "Crore"), (100_000, "Lakh"), (1_000, "Thousand")):
        if n >= divisor:
            parts.append(_below_thousand(n // divisor) + " " + name)
            n %= divisor
    if n:
        parts.append(_below_thousand(n))
    return " ".join(parts)


def amount_in_words(amount):
    amount = q2(D(amount))
    rupees = int(amount)
    paise = int((amount - rupees) * 100)
    words = "Rupees " + _int_to_words(rupees)
    if paise:
        words += " and " + _int_to_words(paise) + " Paise"
    return words + " Only"


# ---------- GSTIN helpers ----------
GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def is_valid_gstin(gstin):
    """Format and checksum check. A blank GSTIN is treated as invalid here; callers should handle blanks separately."""
    g = (gstin or "").strip().upper()
    if len(g) != 15 or any(c not in GSTIN_CHARS for c in g):
        return False
    total = 0
    for i, ch in enumerate(g[:14]):
        product = GSTIN_CHARS.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return GSTIN_CHARS[(36 - total % 36) % 36] == g[14]
