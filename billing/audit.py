import logging

log = logging.getLogger(__name__)


def record(request, action, doc_no="", detail=""):
    """Add a line to the audit log. A problem here is logged but never stops the billing work."""
    try:
        from .models import AuditLog
        user = getattr(request, "user", None)
        AuditLog.objects.create(user_name=(user.get_username() if user is not None and user.is_authenticated else "")[:150],
                                action=action[:40], doc_no=(doc_no or "")[:40], detail=(detail or "")[:300])
    except Exception:
        log.exception("Could not write the audit log")
