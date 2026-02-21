"""
management/commands/purge_test_data.py

Deletes every User, Drop, and related row that was created by the
integration test suite (is_test=True).

Run automatically at deploy via CoreConfig.ready() when the env var
PURGE_TEST_DATA=true is set.  Safe to run manually at any time:

    python manage.py purge_test_data
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from core.models import Drop, UserProfile

User = get_user_model()


class Command(BaseCommand):
    help = "Delete all data created by the integration test suite (is_test=True)."

    def handle(self, *args, **kwargs):
        # Drops owned by test users are caught by the User cascade, but
        # anonymous test drops (owner=None) must be deleted explicitly.
        anon_drops = Drop.objects.filter(is_test=True, owner__isnull=True)
        anon_count = anon_drops.count()
        anon_drops.delete()

        # Deleting the User cascades to UserProfile and all owned drops.
        test_users = User.objects.filter(profile__is_test=True)
        user_count = test_users.count()
        test_users.delete()

        self.stdout.write(
            f"purge_test_data: removed {user_count} test user(s) "
            f"and {anon_count} anonymous test drop(s)."
        )