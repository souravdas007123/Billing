"""Billing ka saara calculation yahin hota hai (Django se independent, isliye test karna aasaan).

Rules:
- Sab kuch Decimal me, float kahin nahi.
- Exclusive: taxable = qty*rate - discount ; GST upar se judta hai.
- Inclusive: line total = qty*rate - discount (final amount); taxable = total*100/(100+gst%).
- Har line ka GST alag round hota hai; CGST = GST/2 (round), SGST = GST - CGST, taaki dono ka sum hamesha GST ke barabar rahe.
- Invoice total nearest rupee tak round-off hota hai; round-off alag line me dikhta hai.
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

TWO = Decimal("0.01")
HUNDRED = Decimal("100")


def D(value, default="0"):
    """Kisi bhi input (str/number/None) ko safely Decimal banata hai. Commas, Rs, % hata deta hai."""
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
    qty, rate, discount_pct, gst_rate = D(qty), D(rate), D(discount_pct), D(gst_rate)
    net = qty * rate * (HUNDRED - discount_pct) / HUNDRED
    if inclusive:
        total = q2(net)
        taxable = q2(total * HUNDRED / (HUNDRED + gst_rate))
        gst = total - taxable
    else:
        taxable = q2(net)
        gst = q2(taxable * gst_rate / HUNDRED)
        total = taxable + gst
    if intra:
        cgst = q2(gst / 2)
        sgst = gst - cgst
        igst = Decimal("0.00")
    else:
        cgst = sgst = Decimal("0.00")
        igst = gst
    return {
        "taxable": taxable,
        "gst": gst,
        "cgst": cgst,
        "sgst": sgst,
        "igst": igst,
        "total": total,
    }


def compute_invoice(items, inclusive, intra):
    """items: list of dicts (qty, rate, discount_pct, gst_rate). Blank rows ke liye zeros aate hain."""
    lines = [
        compute_line(
            it.get("qty"), it.get("rate"), it.get("discount_pct"), it.get("gst_rate"), inclusive, intra
        )
        for it in items
    ]
    zero = Decimal("0.00")
    taxable = sum((l["taxable"] for l in lines), zero)
    cgst = sum((l["cgst"] for l in lines), zero)
    sgst = sum((l["sgst"] for l in lines), zero)
    igst = sum((l["igst"] for l in lines), zero)
    gst_total = cgst + sgst + igst
    exact_total = taxable + gst_total
    total = exact_total.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return {
        "lines": lines,
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
    """Format + checksum check. Blank GSTIN yahan invalid maana jaata hai; caller blank ko alag handle kare."""
    g = (gstin or "").strip().upper()
    if len(g) != 15 or any(c not in GSTIN_CHARS for c in g):
        return False
    total = 0
    for i, ch in enumerate(g[:14]):
        product = GSTIN_CHARS.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return GSTIN_CHARS[(36 - total % 36) % 36] == g[14]
