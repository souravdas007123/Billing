import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0007_cancel_and_credit_note"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("user_name", models.CharField(blank=True, max_length=150)),
                ("action", models.CharField(max_length=40)),
                ("doc_no", models.CharField(blank=True, max_length=40, verbose_name="Bill")),
                ("detail", models.CharField(blank=True, max_length=300)),
            ],
            options={"ordering": ["-at", "-id"]},
        ),
    ]
