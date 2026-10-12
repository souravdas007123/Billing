from django import template

from ..reports import inr

register = template.Library()


@register.filter(name="inr")
def inr_filter(value):
    """Amount with Indian digit grouping and two decimals: 1234567.5 -> 12,34,567.50"""
    try:
        return inr(value)
    except Exception:
        return value
