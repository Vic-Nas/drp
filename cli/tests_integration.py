"""
Integration tests for drp CLI (Django live server required).
Moved from cli/tests.py.
"""

import json
import os
import tempfile
from datetime import timedelta
from pathlib import Path

import requests
from django.contrib.auth.models import User
from django.test import LiveServerTestCase, TestCase, override_settings
from django.utils import timezone

from cli import api, config
from cli.format import human_size, human_time

_STATIC = override_settings(
    STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage'
)

# ... Paste all integration/live server test classes from the original tests.py here ...
# (AuthApiTests, ClipboardApiTests, FileApiTests, AuthDropApiTests, SessionTests, etc.)

# For brevity, the actual test class code should be pasted here as in the original file.
