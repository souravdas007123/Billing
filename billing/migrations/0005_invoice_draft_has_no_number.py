from django.db import migrations, models


def numbered_bills_count_as_submitted(apps, schema_editor):
    """From now on a numbered bill is always a submitted one. Bills that already hold a number keep it, so they are
    marked as submitted on their own date instead of being turned into drafts (which would leave a gap in the series)."""
    Invoice = apps.get_model("billing", "Invoice")
    Invoice.objects.filter(submitted_on__isnull=True, invoice_no__isnull=False).update(submitted_on=models.F("date"))


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0004_invoice_submitted_on"),
    ]

    operations = [
        migrations.AlterField(
            model_name="invoice",
            name="invoice_no",
            field=models.CharField(blank=True, max_length=40, null=True, unique=True),
        ),
        migrations.RunPython(numbered_bills_count_as_submitted, migrations.RunPython.noop),
    ]
