"""
management/commands/purge_test_data.py

Deletes every User, Drop, and related row that was created by the
integration test suite (is_test=True).

Run automatically at deploy via CoreConfig.ready(). Safe to run manually:

    python manage.py purge_test_data
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from core.models import Drop, UserProfile

User = get_user_model()


class Command(BaseCommand):
    help = "Delete all data created by the integration test suite (is_test=True)."

    def handle(self, *args, **kwargs):
        # Explicitly delete drops owned by test users BEFORE deleting the users,
        # so SET_NULL never fires and orphans them with is_test=False.
        test_user_ids = list(
            User.objects.filter(profile__is_test=True).values_list('id', flat=True)
        )
        owned_drops = Drop.objects.filter(owner_id__in=test_user_ids)
        owned_count = owned_drops.count()
        owned_drops.delete()

        # Anonymous drops explicitly flagged as test data.
        anon_drops = Drop.objects.filter(is_test=True, owner__isnull=True)
        anon_count = anon_drops.count()
        anon_drops.delete()

        # Now delete the test users (and anything else that cascades).
        user_count = len(test_user_ids)
        User.objects.filter(id__in=test_user_ids).delete()

        self.stdout.write(
            f"purge_test_data: removed {user_count} test user(s) "
            f"and {owned_count + anon_count} test drop(s)."
        )