from django.db import models
from django.utils import timezone
from datetime import timedelta


class Bin(models.Model):
    key = models.SlugField(max_length=128, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_accessed = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.key

    def total_size(self):
        return sum(f.size for f in self.files.all())

    def is_expired(self):
        expiry = self.last_accessed + timedelta(days=90)
        return timezone.now() > expiry


class BinFile(models.Model):
    bin = models.ForeignKey(Bin, on_delete=models.CASCADE, related_name='files')
    filename = models.CharField(max_length=255)
    file = models.FileField(upload_to='bins/')
    size = models.PositiveBigIntegerField(default=0)  # bytes
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.bin.key}/{self.filename}'


class Clipboard(models.Model):
    key = models.SlugField(max_length=128, unique=True)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.key

    def is_expired(self):
        expiry = self.created_at + timedelta(hours=24)
        return timezone.now() > expiry