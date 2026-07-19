import html as html_lib
import re

from django.utils.html import escape

from .placeholders import PLACEHOLDER_RE


def _substitute(template_str, context, escape_values):
    """Replace {{ key }} with context[key]; unknown keys render as empty string."""

    def replace(match):
        value = context.get(match.group(1), "")
        return escape(value) if escape_values else value

    return PLACEHOLDER_RE.sub(replace, template_str or "")


def render_text(template_str, context):
    """Render for a plain-text context (subject line, text alternative)."""
    return _substitute(template_str, context, escape_values=False)


def render_html(template_str, context):
    """Render for an HTML context; values are HTML-escaped."""
    return _substitute(template_str, context, escape_values=True)


def html_to_text(html):
    """Very small HTML-to-text conversion for the plain-text alternative."""
    text = re.sub(r"<[^>]+>", "", html or "")
    text = html_lib.unescape(text)
    return re.sub(r"[ \t]+", " ", text)
