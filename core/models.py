from django.db import models
from django.utils import timezone
from datetime import timedelta


class Drop(models.Model):
    TEXT = 'text'
    FILE = 'file'
    TYPE_CHOICES = [(TEXT, 'Text'), (FILE, 'File')]

    key = models.SlugField(max_length=128, unique=True)
    kind = models.CharField(max_length=4, choices=TYPE_CHOICES)

    # Text
    content = models.TextField(blank=True, default='')

    # File
    file = models.FileField(upload_to='drp/drops/', blank=True, null=True)
    filename = models.CharField(max_length=255, blank=True, default='')
    filesize = models.PositiveBigIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    last_accessed = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.key} ({self.kind})'

    def is_expired(self):
        if self.kind == self.TEXT:
            return timezone.now() > self.created_at + timedelta(hours=24)
        return timezone.now() > self.last_accessed + timedelta(days=90)

    def touch(self):
        Drop.objects.filter(pk=self.pk).update(last_accessed=timezone.now())

    def hard_delete(self):
        if self.file:
            self.file.delete(save=False)
        self.delete()