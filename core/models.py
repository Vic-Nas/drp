from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import timedelta


# ── Plans ─────────────────────────────────────────────────────────────────────

class Plan:
    ANON    = "anon"
    FREE    = "free"
    STARTER = "starter"
    PRO     = "pro"

    LIMITS = {
        ANON: {
            "label": "Anonymous",
            "price_monthly": 0,
            "max_file_mb": 200,
            "max_text_kb": 500,
            "max_expiry_days": None,
            "storage_gb": None,
            "renewals": 0,
        },
        FREE: {
            "label": "Free",
            "price_monthly": 0,
            "max_file_mb": 200,
            "max_text_kb": 500,
            "max_expiry_days": None,
            "storage_gb": None,
            "renewals": 0,
        },
        STARTER: {
            "label": "Starter",
            "price_monthly": 3,
            "max_file_mb": 1024,
            "max_text_kb": 2048,
            "max_expiry_days": 365,
            "storage_gb": 5,
            "renewals": None,
        },
        PRO: {
            "label": "Pro",
            "price_monthly": 8,
            "max_file_mb": 5120,
            "max_text_kb": 10240,
            "max_expiry_days": 365 * 3,
            "storage_gb": 20,
            "renewals": None,
        },
    }

    @classmethod
    def get(cls, plan_key, field):
        return cls.LIMITS.get(plan_key, cls.LIMITS[cls.ANON])[field]


# ── UserProfile ───────────────────────────────────────────────────────────────

class UserProfile(models.Model):
    PLAN_CHOICES = [
        (Plan.FREE,    "Free"),
        (Plan.STARTER, "Starter ($3/mo)"),
        (Plan.PRO,     "Pro ($8/mo)"),
    ]

    user               = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    plan               = models.CharField(max_length=16, choices=PLAN_CHOICES, default=Plan.FREE)
    plan_since         = models.DateTimeField(null=True, blank=True)
    email_verified     = models.BooleanField(default=False)
    storage_used_bytes = models.PositiveBigIntegerField(default=0)

    ls_customer_id         = models.CharField(max_length=64, blank=True, default="",
                                              help_text="Lemon Squeezy customer ID")
    ls_subscription_id     = models.CharField(max_length=64, blank=True, default="",
                                              help_text="Lemon Squeezy subscription ID")
    ls_subscription_status = models.CharField(max_length=32, blank=True, default="",
                                              help_text="active, cancelled, expired, etc.")

    def __str__(self):
        return f"{self.user.username} [{self.plan}]"

    @property
    def is_paid(self):
        return self.plan in (Plan.STARTER, Plan.PRO)

    @property
    def storage_quota_bytes(self):
        gb = Plan.get(self.plan, "storage_gb")
        return gb * 1024 ** 3 if gb else None

    @property
    def storage_used_gb(self):
        return self.storage_used_bytes / (1024 ** 3)

    @property
    def storage_quota_gb(self):
        return Plan.get(self.plan, "storage_gb")

    def storage_available_bytes(self):
        quota = self.storage_quota_bytes
        return max(0, quota - self.storage_used_bytes) if quota is not None else None

    def recalc_storage(self):
        total = self.user.drops.aggregate(total=models.Sum("filesize"))["total"] or 0
        UserProfile.objects.filter(pk=self.pk).update(storage_used_bytes=total)
        self.storage_used_bytes = total

    def max_expiry_days(self):
        return Plan.get(self.plan, "max_expiry_days")

    def max_file_mb(self):
        return Plan.get(self.plan, "max_file_mb")

    def max_text_kb(self):
        return Plan.get(self.plan, "max_text_kb")


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)


# ── Drop ──────────────────────────────────────────────────────────────────────

class Drop(models.Model):
    NS_CLIPBOARD = "c"
    NS_FILE      = "f"
    NS_CHOICES   = [("c", "Clipboard"), ("f", "File")]

    TEXT = "text"
    FILE = "file"
    TYPE_CHOICES = [(TEXT, "Text"), (FILE, "File")]

    ns   = models.CharField(max_length=1, choices=NS_CHOICES, default=NS_CLIPBOARD, db_index=True)
    key  = models.CharField(max_length=120, db_index=True)
    kind = models.CharField(max_length=4, choices=TYPE_CHOICES)

    owner = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="drops",
    )

    # Token set on anonymous drops so they can be claimed on signup/login
    anon_token = models.CharField(max_length=64, null=True, blank=True, db_index=True)

    content = models.TextField(blank=True, default="")

    # file_url       — presigned GET URLs expire; we regenerate on demand from
    #                  (ns, key) via b2.presigned_get().  This field now stores
    #                  the *permanent* B2 download base URL if needed for legacy
    #                  records, but is otherwise unused for new drops.
    # file_public_id — stores the B2 object key, e.g. "drops/f/report"
    file_url       = models.URLField(blank=True, default="")
    file_public_id = models.CharField(max_length=512, blank=True, default="")
    filename       = models.CharField(max_length=255, blank=True, default="")
    filesize       = models.PositiveBigIntegerField(default=0)

    created_at        = models.DateTimeField(auto_now_add=True)
    last_accessed_at  = models.DateTimeField(null=True, blank=True, db_index=True)
    max_lifetime_secs = models.PositiveIntegerField(null=True, blank=True)

    locked        = models.BooleanField(default=False)
    locked_until  = models.DateTimeField(null=True, blank=True)
    expires_at    = models.DateTimeField(null=True, blank=True)
    renewal_count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("ns", "key")]

    def __str__(self):
        prefix = "f/" if self.ns == self.NS_FILE else ""
        return f"/{prefix}{self.key}/ ({self.kind})"

    @property
    def owner_plan(self):
        if self.owner_id and hasattr(self.owner, "profile"):
            return self.owner.profile.plan
        return Plan.ANON

    @property
    def is_paid_drop(self):
        if self.owner_id and hasattr(self.owner, "profile"):
            return self.owner.profile.is_paid
        return False

    def is_expired(self):
        now = timezone.now()

        if self.expires_at:
            return now > self.expires_at

        if self.max_lifetime_secs:
            if (now - self.created_at).total_seconds() > self.max_lifetime_secs:
                return True

        if self.ns == self.NS_CLIPBOARD:
            idle_hours = 24 if not self.owner_id else 48
            ref = self.last_accessed_at or self.created_at
            return (now - ref) > timedelta(hours=idle_hours)

        return (now - self.created_at) > timedelta(days=90)

    # ── touch (debounced) ─────────────────────────────────────────────────────

    #: Skip the DB write if last_accessed_at is within this many seconds.
    #: Prevents a write on every GET for hot drops without affecting expiry logic
    #: (idle timeout is 24–48h so 5 min is invisible).
    TOUCH_DEBOUNCE_SECS = 300  # 5 minutes

    def touch(self):
        now = timezone.now()
        if (
            self.last_accessed_at is not None
            and (now - self.last_accessed_at).total_seconds() < self.TOUCH_DEBOUNCE_SECS
        ):
            return  # recent enough — skip the write
        Drop.objects.filter(pk=self.pk).update(last_accessed_at=now)
        self.last_accessed_at = now

    def renew(self):
        if not self.expires_at:
            return
        duration = self.expires_at - self.created_at
        self.expires_at = timezone.now() + duration
        self.renewal_count += 1
        self.save(update_fields=["expires_at", "renewal_count"])

    def recalculate_expiry_for_plan(self, plan):
        max_days = Plan.get(plan, "max_expiry_days")
        if max_days and self.expires_at:
            new_expiry = self.created_at + timedelta(days=max_days)
            if new_expiry > self.expires_at:
                self.expires_at = new_expiry
                self.save(update_fields=["expires_at"])

    def hard_delete(self):
        """
        Delete the Drop record and, for file drops, remove the object from B2.
        Also adjusts owner storage accounting.
        """
        if self.ns == self.NS_FILE and self.file_public_id:
            # file_public_id stores the B2 object key ("drops/f/<key>")
            # We call delete_object directly with ns+key rather than the stored
            # public_id so the logic stays consistent even if the field is stale.
            try:
                from core.views.b2 import delete_object
                delete_object(self.ns, self.key)
            except Exception:
                pass  # never let storage errors block DB cleanup

        if self.owner_id and self.filesize:
            from django.db import models as db_models
            UserProfile.objects.filter(user_id=self.owner_id).update(
                storage_used_bytes=db_models.F("storage_used_bytes") - self.filesize
            )
        self.delete()

    def can_edit(self, user):
        if self.locked:
            return getattr(user, "is_authenticated", False) and self.owner_id == user.pk
        if self.is_creation_locked():
            return False
        return True

    def is_creation_locked(self):
        return bool(self.locked_until and timezone.now() < self.locked_until)

    def download_url(self, expires_in: int = 3600) -> str:
        """
        Return a fresh presigned B2 GET URL for this file drop.
        Raises if called on a text drop.
        """
        if self.ns != self.NS_FILE:
            raise ValueError("download_url() called on non-file drop")
        from core.views.b2 import presigned_get
        return presigned_get(self.ns, self.key, filename=self.filename, expires_in=expires_in)


# ── SavedDrop ─────────────────────────────────────────────────────────────────

class SavedDrop(models.Model):
    """
    A bookmark — records that a user wants to track a drop by key.
    No content is stored. The drop may or may not still exist on the server.
    Saving a drop does not grant any ownership or edit permissions.
    """
    user     = models.ForeignKey(User, on_delete=models.CASCADE, related_name="saved_drops")
    ns       = models.CharField(max_length=1, choices=Drop.NS_CHOICES, default=Drop.NS_CLIPBOARD)
    key      = models.CharField(max_length=120)
    saved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "ns", "key")]
        ordering = ["-saved_at"]

    def __str__(self):
        prefix = "f/" if self.ns == Drop.NS_FILE else ""
        return f"{self.user.email} → /{prefix}{self.key}/"

    @property
    def url_path(self):
        if self.ns == Drop.NS_FILE:
            return f"/f/{self.key}/"
        return f"/{self.key}/"