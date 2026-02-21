from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # Warm the B2 client once at worker startup so the first request
        # doesn't pay the boto3 initialization cost (~800ms–1s).
        try:
            from core.views import b2
            b2._b2()
        except Exception:
            pass  # never block startup if B2 credentials are missing

        # Always purge test data on startup — is_test=True is only set by the
        # integration suite, so this is a no-op in production unless tests ran
        # against it directly. No env var gate needed.
        try:
            from django.core.management import call_command
            call_command('purge_test_data', verbosity=0)
        except Exception:
            pass  # never block startup