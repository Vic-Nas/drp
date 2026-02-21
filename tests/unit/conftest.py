"""
tests/unit/conftest.py

Force an in-memory SQLite DB for all unit tests, regardless of any DB_URL
environment variable. This ensures unit tests never touch the real database.
"""

import django
from django.conf import settings


def pytest_configure(config):
    settings.DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }