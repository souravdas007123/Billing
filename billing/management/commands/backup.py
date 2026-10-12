from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from billing.backup import daily_backup, prune, snapshot


class Command(BaseCommand):
    help = "Copy the SQLite database to the backup folder (settings.BACKUP_DIR). Use --now for an extra copy of today."

    def add_arguments(self, parser):
        parser.add_argument("--now", action="store_true", help="overwrite today's backup with a fresh copy")

    def handle(self, *args, **opts):
        db = settings.DATABASES["default"]
        if not db["ENGINE"].endswith("sqlite3"):
            raise CommandError("Backups are only built in for SQLite.")
        import datetime
        today = datetime.date.today()
        if opts["now"]:
            dest = snapshot(db["NAME"], settings.BACKUP_DIR / f"db-{today:%Y-%m-%d}.sqlite3")
            prune(settings.BACKUP_DIR, settings.BACKUP_KEEP)
        else:
            dest = daily_backup(db["NAME"], settings.BACKUP_DIR, today, settings.BACKUP_KEEP)
        self.stdout.write(f"Backup written: {dest}" if dest else "Today's backup already exists (use --now for a fresh copy).")
