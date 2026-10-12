from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="invoice",
            name="price_mode",
            field=models.CharField(
                choices=[
                    ("AMT", "Amount entry (GST included)"),
                    ("EXCL", "GST excluded"),
                    ("INCL", "GST included"),
                ],
                default="EXCL",
                max_length=4,
            ),
        ),
    ]
