from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from core.models import Drop


class Command(BaseCommand):
    help = 'Delete expired drops'

    def handle(self, *args, **kwargs):
        all_drops = Drop.objects.all()
        deleted = 0
        for drop in all_drops:
            if drop.is_expired():
                drop.hard_delete()
                deleted += 1
        self.stdout.write(f'Deleted {deleted} expired drops')