"""
core/templatetags/drop_tags.py

Custom template filters for drop-related logic.
"""

from django import template
from core.models import SavedDrop

register = template.Library()


@register.filter
def is_saved_by(drop, user):
    """
    Usage: {% if drop|is_saved_by:user %}

    Returns True if the given user has bookmarked this drop.
    """
    if not user or not user.is_authenticated:
        return False
    return SavedDrop.objects.filter(user=user, ns=drop.ns, key=drop.key).exists()