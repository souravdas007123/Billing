import re

from django.conf import settings
from django.db import models
from django.utils import timezone

# GST state codes (name -> code)
STATE_CODES = {
    "Jammu and Kashmir": "01", "Himachal Pradesh": "02", "Punjab": "03", "Chandigarh": "04",
    "Uttarakhand": "05", "Haryana": "06", "Delhi": "07", "Rajasthan": "08", "Uttar Pradesh": "09",
    "Bihar": "10", "Sikkim": "11", "Arunachal Pradesh": "12", "Nagaland": "13", "Manipur": "14",
    "Mizoram": "15", "Tripura": "16", "Meghalaya": "17", "Assam": "18", "West Bengal": "19",
    "Jharkhand": "20", "Odisha": "21", "Chhattisgarh": "22", "Madhya Pradesh": "23", "Gujarat": "24",
    "Dadra and Nagar Haveli and Daman and Diu": "26", "Maharashtra": "27", "Karnataka": "29",
    "Goa": "30", "Lakshadweep": "31", "Kerala": "32", "Tamil Nadu": "33", "Puducherry": "34",
    "Andaman and Nicobar Islands": "35", "Telangana": "36", "Andhra Pradesh": "37", "Ladakh": "38",
}
STATE_CHOICES = [(name, name) for name in STATE_CODES]
CODE_TO_STATE = {code: name for name, code in STATE_CODES.items()}

PRICE_MODES = [
    ("AMT", "Amount entry (GST included)"),
    ("EXCL", "GST excluded"),
    ("INCL", "GST included"),
]


# The kind of document. A bill of supply (no GST charged: composition dealer, exempt goods) and an estimate (not a tax
# document at all) each have their own number series, so the tax invoice series stays unbroken.
DOC_TYPES = [
    ("TAX", "Tax invoice"),
    ("SUPPLY", "Bill of supply (no GST)"),
    ("EST", "Estimate (no GST, not a tax document)"),
    ("CN", "Credit note (return or correction)"),
]
DOC_PREFIXES = {"SUPPLY": "BOS", "EST": "EST", "CN": "CN"}  # a tax invoice uses the firm's own prefix
GST_DOC_TYPES = ("TAX", "CN")  # the types that charge GST (a credit note reduces the GST of an earlier invoice)


def doc_prefix(firm, doc_type):
    return firm.invoice_prefix if doc_type == "TAX" else DOC_PREFIXES[doc_type]


def state_from_gstin(gstin):
    g = (gstin or "").strip()
    return CODE_TO_STATE.get(g[:2], "") if len(g) >= 2 else ""


def image_check(f):
    """Logo / signature: only PNG or JPG, at most 1 MB."""
    from django.core.exceptions import ValidationError
    name = (getattr(f, "name", "") or "").lower()
    if not name.endswith((".png", ".jpg", ".jpeg")):
        raise ValidationError("Upload a PNG or JPG image.")
    if getattr(f, "size", 0) > 1024 * 1024:
        raise ValidationError("The image is larger than 1 MB. Please use a smaller one.")


class Firm(models.Model):
    """Your own company details (a single record). Fill it in from the admin site."""

    name = models.CharField(max_length=200, default="My Company")
    address = models.TextField(blank=True)
    gstin = models.CharField("GSTIN", max_length=15, blank=True)
    state = models.CharField(max_length=60, choices=STATE_CHOICES, default="West Bengal")
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    bank_details = models.TextField(blank=True, help_text="Printed at the bottom of the invoice")
    terms = models.TextField(blank=True, help_text="Terms & conditions")
    invoice_prefix = models.CharField(max_length=20, default="INV")
    logo = models.FileField(upload_to="firm/", blank=True, validators=[image_check], help_text="PNG or JPG, up to 1 MB. Printed at the top of the invoice.")
    signature = models.FileField(upload_to="firm/", blank=True, validators=[image_check], help_text="PNG or JPG, up to 1 MB (a scan of the signature on white or transparent background).")
    upi_id = models.CharField("UPI ID", max_length=80, blank=True, help_text="For example shopname@okaxis. A payment QR with the bill total is printed on bills.")

    class Meta:
        verbose_name = "Firm"

    def clean(self):
        from django.core.exceptions import ValidationError
        from .share import valid_upi_id
        if self.upi_id and not valid_upi_id(self.upi_id):
            raise ValidationError({"upi_id": "Enter a valid UPI ID such as shopname@okaxis."})

    def __str__(self):
        return self.name

    @classmethod
    def get(cls):
        return cls.objects.first() or cls.objects.create()


class Party(models.Model):
    name = models.CharField(max_length=200, unique=True)
    address = models.TextField(blank=True)
    gstin = models.CharField("GSTIN", max_length=15, blank=True)
    state = models.CharField(max_length=60, choices=STATE_CHOICES, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Parties"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.gstin = (self.gstin or "").strip().upper()
        if self.gstin and not self.state:
            self.state = state_from_gstin(self.gstin)
        super().save(*args, **kwargs)


class Product(models.Model):
    """Optional item master: typing a description fills in the HSN, unit, rate and GST automatically."""

    name = models.CharField(max_length=300, unique=True)
    hsn = models.CharField("HSN/SAC", max_length=12, blank=True)
    unit = models.CharField(max_length=20, default="Nos")
    rate = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=settings.DEFAULT_GST_RATE)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


def financial_year_label(d):
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


class Invoice(models.Model):
    # A bill that is not submitted yet is a draft and has no invoice number. The number is given when it is submitted,
    # so the numbers in use always form an unbroken series.
    invoice_no = models.CharField(max_length=40, unique=True, null=True, blank=True)
    date = models.DateField(default=timezone.localdate)
    party = models.ForeignKey(Party, null=True, blank=True, on_delete=models.SET_NULL)

    # Party details are stored on the invoice as a snapshot, so editing a party later does not change old invoices.
    party_name = models.CharField(max_length=200)
    party_address = models.TextField(blank=True)
    party_gstin = models.CharField(max_length=15, blank=True)
    party_state = models.CharField(max_length=60, blank=True)
    party_phone = models.CharField(max_length=40, blank=True)
    party_email = models.EmailField(blank=True)

    place_of_supply = models.CharField(max_length=60, blank=True)
    doc_type = models.CharField(max_length=6, choices=DOC_TYPES, default="TAX")
    price_mode = models.CharField(max_length=4, choices=PRICE_MODES, default="EXCL")
    # A credit note names the invoice it corrects.
    ref_no = models.CharField("Against invoice no.", max_length=40, blank=True)
    ref_date = models.DateField("Against invoice date", null=True, blank=True)
    # A numbered bill is never deleted: a wrong one is cancelled, and its number stays in the series.
    status = models.CharField(max_length=10, choices=[("ACTIVE", "Active"), ("CANCELLED", "Cancelled")], default="ACTIVE")
    cancelled_on = models.DateField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=200, blank=True)
    is_intra_state = models.BooleanField(default=True)

    taxable_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    cgst = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    sgst = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    igst = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    round_off = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    notes = models.TextField(blank=True)
    # The day the bill was handed over. Empty means the bill is made but not submitted yet.
    submitted_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]
        permissions = [("cancel_invoice", "Can cancel invoices")]
        indexes = [
            models.Index(fields=["date"], name="inv_date_idx"),
            models.Index(fields=["doc_type", "date"], name="inv_type_date_idx"),
            models.Index(fields=["party_name"], name="inv_party_idx"),
            models.Index(fields=["status"], name="inv_status_idx"),
            models.Index(fields=["submitted_on"], name="inv_submitted_idx"),
        ]

    def __str__(self):
        return f"{self.invoice_no or 'Draft'} - {self.party_name}"

    @property
    def is_cancelled(self):
        return self.status == "CANCELLED"

    @property
    def charges_gst(self):
        return self.doc_type in GST_DOC_TYPES

    @property
    def is_pending(self):
        return self.submitted_on is None

    @property
    def is_draft(self):
        return self.invoice_no is None

    @property
    def gst_total(self):
        return self.cgst + self.sgst + self.igst

    @classmethod
    def next_number(cls, prefix, on_date=None):
        """Next number, e.g. PREFIX/26-27/0001. The series restarts each financial year (April to March)."""
        on_date = on_date or timezone.localdate()
        series = f"{prefix}/{financial_year_label(on_date)}/"
        last = 0
        for no in cls.objects.filter(invoice_no__startswith=series).values_list("invoice_no", flat=True):
            m = re.search(r"(\d+)$", no)
            if m:
                last = max(last, int(m.group(1)))
        return f"{series}{last + 1:04d}"


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, related_name="items", on_delete=models.CASCADE)
    sr = models.PositiveIntegerField(default=1)
    description = models.CharField(max_length=300)
    hsn = models.CharField(max_length=12, blank=True)
    qty = models.DecimalField(max_digits=14, decimal_places=3)
    unit = models.CharField(max_length=20, blank=True)
    rate = models.DecimalField(max_digits=14, decimal_places=4)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2)
    taxable = models.DecimalField(max_digits=14, decimal_places=2)
    gst_amount = models.DecimalField(max_digits=14, decimal_places=2)
    line_total = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["sr"]

    def __str__(self):
        return f"{self.invoice.invoice_no} #{self.sr} {self.description}"


class AuditLog(models.Model):
    """Who did what and when. Written by the app only; it cannot be edited or deleted in the admin site."""
    at = models.DateTimeField(default=timezone.now, db_index=True)
    user_name = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=40)
    doc_no = models.CharField("Bill", max_length=40, blank=True)
    detail = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-at", "-id"]

    def __str__(self):
        return f"{self.at:%d-%m-%Y %H:%M} {self.user_name} {self.action} {self.doc_no}"
