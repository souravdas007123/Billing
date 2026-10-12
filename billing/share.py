"""Links for sharing a bill and the UPI payment string. Pure functions (no Django), so they are easy to test."""
import re
from decimal import Decimal
from urllib.parse import quote, urlencode


def phone_digits(phone, country="91"):
    """'098765 43210' / '+91 98765-43210' -> '919876543210'. None when it does not look like a phone number."""
    d = re.sub(r"\D", "", phone or "")
    if d.startswith("00"):
        d = d[2:]
    if len(d) == 11 and d.startswith("0"):
        d = d[1:]
    if len(d) == 10:
        d = country + d
    return d if 11 <= len(d) <= 15 else None


def whatsapp_url(phone, text):
    """A wa.me link that opens WhatsApp with the message typed in (with the number when there is a usable one)."""
    number = phone_digits(phone)
    return f"https://wa.me/{number or ''}?text={quote(text)}"


def mailto_url(email, subject, body):
    return f"mailto:{quote((email or '').strip())}?subject={quote(subject)}&body={quote(body)}"


def valid_upi_id(vpa):
    return bool(re.fullmatch(r"[A-Za-z0-9._\-]{2,64}@[A-Za-z][A-Za-z0-9.\-]{1,32}", (vpa or "").strip()))


def upi_uri(vpa, payee, amount, note=""):
    """The string a UPI app reads from a QR code. The amount is fixed to the bill total."""
    params = {"pa": vpa.strip(), "pn": payee[:60], "am": f"{Decimal(amount):.2f}", "cu": "INR"}
    if note:
        params["tn"] = note[:50]
    return "upi://pay?" + urlencode(params, quote_via=quote)


def qr_svg(data):
    """Inline SVG of a QR code, or '' when the 'segno' package is not installed (the bill then prints without a QR)."""
    try:
        import segno
        return segno.make(data, error="m").svg_inline(scale=3, border=1, dark="#000000", light="#ffffff")
    except Exception:
        return ""
