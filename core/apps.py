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

        # Purge test data left by the integration suite.
        # Only runs when PURGE_TEST_DATA=true is set — never in production
        # unless you explicitly opt in.
        import os
        if os.environ.get('PURGE_TEST_DATA', '').lower() in ('1', 'true', 'yes'):
            try:
                from django.core.management import call_command
                call_command('purge_test_data', verbosity=0)
            except Exception:
                pass  # never block startup