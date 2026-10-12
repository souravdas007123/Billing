import billing.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0009_invoice_indexes"),
    ]

    operations = [
        migrations.AddField(model_name="firm", name="logo", field=models.FileField(blank=True, help_text="PNG or JPG, up to 1 MB. Printed at the top of the invoice.", upload_to="firm/", validators=[billing.models.image_check])),
        migrations.AddField(model_name="firm", name="signature", field=models.FileField(blank=True, help_text="PNG or JPG, up to 1 MB (a scan of the signature on white or transparent background).", upload_to="firm/", validators=[billing.models.image_check])),
        migrations.AddField(model_name="firm", name="upi_id", field=models.CharField(blank=True, help_text="For example shopname@okaxis. A payment QR with the bill total is printed on bills.", max_length=80, verbose_name="UPI ID")),
    ]
