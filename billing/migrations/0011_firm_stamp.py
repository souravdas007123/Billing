import billing.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0010_firm_logo_signature_upi"),
    ]

    operations = [
        migrations.AddField(model_name="firm", name="stamp", field=models.FileField(blank=True, help_text="PNG or JPG, up to 1 MB (company stamp / seal; a PNG with a transparent background looks best). Printed next to the signature.", upload_to="firm/", validators=[billing.models.image_check])),
    ]
