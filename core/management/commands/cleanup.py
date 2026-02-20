from django.core.management.base import BaseCommand
from core.models import Drop


class Command(BaseCommand):
    help = "Delete expired drops (DB records + B2 objects)"

    def handle(self, *args, **kwargs):
        all_drops = Drop.objects.select_related("owner__profile").all()
        deleted = 0
        for drop in all_drops:
            if drop.is_expired():
                drop.hard_delete()   # deletes B2 object + adjusts storage accounting
                deleted += 1
        self.stdout.write(f"Deleted {deleted} expired drop(s).")