from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import UserProfile, Drop


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'profile'
    fields = ('plan', 'plan_since', 'storage_used_bytes', 'email_verified')
    readonly_fields = ('storage_used_bytes',)


class UserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)
    list_display = ('email', 'get_plan', 'get_storage', 'date_joined', 'is_active')
    search_fields = ('email', 'username')

    @admin.display(description='plan')
    def get_plan(self, obj):
        return obj.profile.plan if hasattr(obj, 'profile') else '—'

    @admin.display(description='storage used')
    def get_storage(self, obj):
        if not hasattr(obj, 'profile'):
            return '—'
        mb = obj.profile.storage_used_bytes / (1024 ** 2)
        return f'{mb:.1f} MB'


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(Drop)
class DropAdmin(admin.ModelAdmin):
    list_display = ('key', 'kind', 'owner', 'locked', 'filesize', 'created_at', 'expires_at')
    list_filter = ('kind', 'locked')
    search_fields = ('key', 'owner__email', 'filename')
    readonly_fields = ('created_at', 'last_accessed', 'renewal_count')
    raw_id_fields = ('owner',)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'storage_used_bytes', 'email_verified', 'plan_since')
    list_filter = ('plan', 'email_verified')
    search_fields = ('user__email',)
    actions = ['upgrade_to_starter', 'upgrade_to_pro', 'downgrade_to_free']

    @admin.action(description='Upgrade to Starter')
    def upgrade_to_starter(self, request, queryset):
        from django.utils import timezone
        from .models import Plan
        queryset.update(plan=Plan.STARTER, plan_since=timezone.now())
        # Recalculate drop expiries
        for profile in queryset:
            for drop in profile.user.drops.filter(expires_at__isnull=False):
                drop.recalculate_expiry_for_plan(Plan.STARTER)

    @admin.action(description='Upgrade to Pro')
    def upgrade_to_pro(self, request, queryset):
        from django.utils import timezone
        from .models import Plan
        queryset.update(plan=Plan.PRO, plan_since=timezone.now())
        for profile in queryset:
            for drop in profile.user.drops.filter(expires_at__isnull=False):
                drop.recalculate_expiry_for_plan(Plan.PRO)

    @admin.action(description='Downgrade to Free')
    def downgrade_to_free(self, request, queryset):
        from .models import Plan
        queryset.update(plan=Plan.FREE, plan_since=None)