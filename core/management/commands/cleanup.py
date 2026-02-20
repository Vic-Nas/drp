from django.core.management.base import BaseCommand
from core.models import Drop


class Command(BaseCommand):
    help = "Delete expired drops (DB records + B2 objects)"

    def handle(self, *args, **kwargs):
        all_drops = Drop.objects.select_related("owner__profile").all()
        deleted = 0
        b2_failed = 0
        for drop in all_drops:
            if drop.is_expired():
                ok = drop.hard_delete()
                if ok:
                    deleted += 1
                else:
                    # B2 delete failed — DB record preserved, error already logged.
                    # Will be retried on the next cleanup run.
                    b2_failed += 1

        msg = f"Deleted {deleted} expired drop(s)."
        if b2_failed:
            msg += f" {b2_failed} drop(s) could not be removed from B2 storage (will retry)."
            self.stderr.write(msg)
        else:
            self.stdout.write(msg)