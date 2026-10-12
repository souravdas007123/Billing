import logging

from django.conf import settings
from django.utils import timezone

from .backup import daily_backup

log = logging.getLogger(__name__)
_done_on = None  # the day this process last checked for a backup


class DailyBackupMiddleware:
    """On the first request of the day, copy the database to BACKUP_DIR (the last BACKUP_KEEP days are kept)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        global _done_on
        today = timezone.localdate()
        if _done_on != today and getattr(settings, "BACKUP_ENABLED", True):
            _done_on = today
            db = settings.DATABASES["default"]
            if db["ENGINE"].endswith("sqlite3") and str(db["NAME"]) != ":memory:":
                try:
                    daily_backup(db["NAME"], settings.BACKUP_DIR, today, settings.BACKUP_KEEP)
                except Exception:  # a failed backup must never stop billing
                    log.exception("Daily backup failed")
        return self.get_response(request)
