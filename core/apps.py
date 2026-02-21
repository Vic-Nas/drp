import os

from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # Warm the B2 client once at worker startup so the first request
        # does not pay the boto3 initialization cost (~800ms-1s).
        try:
            from core.views import b2
            b2._b2()
        except Exception:
            pass  # never block startup if B2 credentials are missing

        # Purge test data once per deploy, not once per worker.
        # RUN_MAIN=true is set by Django's dev reloader for the parent process.
        # Under gunicorn it is not set at all — so we check for a PURGE_DONE
        # sentinel file to ensure only one worker runs the purge.
        sentinel = '/tmp/drp_purge_done'
        if not os.path.exists(sentinel):
            try:
                open(sentinel, 'w').close()
                from django.core.management import call_command
                call_command('purge_test_data', verbosity=0)
            except Exception:
                pass  # never block startup