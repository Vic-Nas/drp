from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import timedelta


# ── Plans ─────────────────────────────────────────────────────────────────────

class Plan:
    """
    Central place for all plan limits. Change here → enforced everywhere.
    """
    ANON = 'anon'
    FREE = 'free'
    STARTER = 'starter'
    PRO = 'pro'

    LIMITS = {
        ANON: {
            'label': 'Anonymous',
            'price_monthly': 0,
            'max_file_mb': 200,
            'max_text_kb': 500,
            'max_expiry_days': None,       # access-based, 90d
            'storage_gb': None,            # no quota
            'renewals': 0,
        },
        FREE: {
            'label': 'Free',
            'price_monthly': 0,
            'max_file_mb': 200,
            'max_text_kb': 500,
            'max_expiry_days': None,       # access-based, 90d
            'storage_gb': None,
            'renewals': 0,
        },
        STARTER: {
            'label': 'Starter',
            'price_monthly': 3,
            'max_file_mb': 1024,           # 1 GB per file
            'max_text_kb': 2048,           # 2 MB
            'max_expiry_days': 365,        # up to 1 year from creation
            'storage_gb': 5,
            'renewals': None,              # unlimited
        },
        PRO: {
            'label': 'Pro',
            'price_monthly': 8,
            'max_file_mb': 5120,           # 5 GB per file
            'max_text_kb': 10240,          # 10 MB
            'max_expiry_days': 365 * 3,    # up to 3 years from creation
            'storage_gb': 20,
            'renewals': None,              # unlimited
        },
    }

    @classmethod
    def get(cls, plan_key, field):
        return cls.LIMITS.get(plan_key, cls.LIMITS[cls.ANON])[field]


# ── UserProfile ───────────────────────────────────────────────────────────────

class UserProfile(models.Model):
    PLAN_CHOICES = [
        (Plan.FREE, 'Free'),
        (Plan.STARTER, 'Starter ($3/mo)'),
        (Plan.PRO, 'Pro ($8/mo)'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    plan = models.CharField(max_length=16, choices=PLAN_CHOICES, default=Plan.FREE)
    plan_since = models.DateTimeField(null=True, blank=True)   # when they last upgraded
    email_verified = models.BooleanField(default=False)

    # Computed storage usage (updated on save/delete of drops)
    storage_used_bytes = models.PositiveBigIntegerField(default=0)

    def __str__(self):
        return f'{self.user.username} [{self.plan}]'

    @property
    def is_paid(self):
        return self.plan in (Plan.STARTER, Plan.PRO)

    @property
    def storage_quota_bytes(self):
        gb = Plan.get(self.plan, 'storage_gb')
        if gb is None:
            return None
        return gb * 1024 ** 3

    @property
    def storage_used_gb(self):
        return self.storage_used_bytes / (1024 ** 3)

    @property
    def storage_quota_gb(self):
        return Plan.get(self.plan, 'storage_gb')

    def storage_available_bytes(self):
        quota = self.storage_quota_bytes
        if quota is None:
            return None
        return max(0, quota - self.storage_used_bytes)

    def recalc_storage(self):
        total = self.user.drops.aggregate(
            total=models.Sum('filesize')
        )['total'] or 0
        UserProfile.objects.filter(pk=self.pk).update(storage_used_bytes=total)
        self.storage_used_bytes = total

    def max_expiry_days(self):
        return Plan.get(self.plan, 'max_expiry_days')

    def max_file_mb(self):
        return Plan.get(self.plan, 'max_file_mb')

    def max_text_kb(self):
        return Plan.get(self.plan, 'max_text_kb')


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)


# ── Drop ──────────────────────────────────────────────────────────────────────

class Drop(models.Model):
    TEXT = 'text'
    FILE = 'file'
    TYPE_CHOICES = [(TEXT, 'Text'), (FILE, 'File')]

    key = models.SlugField(max_length=128, unique=True)
    kind = models.CharField(max_length=4, choices=TYPE_CHOICES)

    owner = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='drops',
    )

    # Text
    content = models.TextField(blank=True, default='')

    # File
    file = models.FileField(upload_to='drops/', blank=True, null=True)
    filename = models.CharField(max_length=255, blank=True, default='')
    filesize = models.PositiveBigIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    last_accessed = models.DateTimeField(auto_now_add=True)

    # Paid-drop fields
    locked = models.BooleanField(default=False)          # only owner can edit/delete
    locked_until = models.DateTimeField(null=True, blank=True)  # 24h creation window (anon)
    expires_at = models.DateTimeField(null=True, blank=True)    # explicit expiry for paid drops
    renewal_count = models.PositiveIntegerField(default=0)

    # ── Ownership ─────────────────────────────────────────────────────────────

    @property
    def owner_plan(self):
        if self.owner_id and hasattr(self.owner, 'profile'):
            return self.owner.profile.plan
        return Plan.ANON

    @property
    def is_paid_drop(self):
        if self.owner_id and hasattr(self.owner, 'profile'):
            return self.owner.profile.is_paid
        return False

    # ── Expiry ────────────────────────────────────────────────────────────────

    def is_expired(self):
        if self.expires_at:
            return timezone.now() > self.expires_at
        # Anon / free fallback: access-based
        if self.kind == self.TEXT:
            return timezone.now() > self.created_at + timedelta(hours=24)
        return timezone.now() > self.last_accessed + timedelta(days=90)

    def renew(self):
        """Reset expiry clock from now, keeping same duration."""
        if not self.expires_at:
            return
        duration = self.expires_at - self.created_at
        self.expires_at = timezone.now() + duration
        self.renewal_count += 1
        self.save(update_fields=['expires_at', 'renewal_count'])

    def recalculate_expiry_for_plan(self, plan):
        """
        Called when owner upgrades. Sets expires_at to
        created_at + new plan max (bounded to plan limit).
        """
        max_days = Plan.get(plan, 'max_expiry_days')
        if max_days and self.expires_at:
            new_expiry = self.created_at + timedelta(days=max_days)
            if new_expiry > self.expires_at:
                self.expires_at = new_expiry
                self.save(update_fields=['expires_at'])

    # ── Permissions ───────────────────────────────────────────────────────────

    def can_edit(self, user):
        if self.locked:
            return user.is_authenticated and self.owner_id == user.pk
        return True

    def is_creation_locked(self):
        """24h window after creation (anon drops only)."""
        return self.locked_until and timezone.now() < self.locked_until

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def touch(self):
        Drop.objects.filter(pk=self.pk).update(last_accessed=timezone.now())

    def hard_delete(self):
        if self.file:
            self.file.delete(save=False)
        # Update owner storage
        if self.owner_id and self.filesize:
            UserProfile.objects.filter(user_id=self.owner_id).update(
                storage_used_bytes=models.F('storage_used_bytes') - self.filesize
            )
        self.delete()

    def __str__(self):
        return f'{self.key} ({self.kind})'