from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from core.models import Bin, Clipboard


class Command(BaseCommand):
    help = 'Delete expired clipboards (24h) and inactive bins (90 days)'

    def handle(self, *args, **kwargs):
        # Clipboards older than 24h
        clip_cutoff = timezone.now() - timedelta(hours=24)
        deleted_clips, _ = Clipboard.objects.filter(created_at__lt=clip_cutoff).delete()
        self.stdout.write(f'Deleted {deleted_clips} expired clipboards')

        # Bins inactive for 90 days
        bin_cutoff = timezone.now() - timedelta(days=90)
        expired_bins = Bin.objects.filter(last_accessed__lt=bin_cutoff)
        count = expired_bins.count()
        for b in expired_bins:
            for f in b.files.all():
                f.file.delete(save=False)  # delete from cloudinary
            b.delete()
        self.stdout.write(f'Deleted {count} inactive bins')