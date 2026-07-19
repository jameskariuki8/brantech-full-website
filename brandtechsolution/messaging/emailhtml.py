"""Prepare authored HTML for delivery to email clients.

Two stages, both applied when a template or campaign body is saved:

1. sanitize_email_html - strip anything unsafe, keep email-safe markup.
2. inline_email_css    - inline BASE_EMAIL_CSS, because Outlook and Gmail
                         ignore <style> blocks and external CSS classes.

The sanitized (non-inlined) result is stored as `body_source` for editing;
the inlined result is stored as `body_html` and is what gets sent.
"""
import css_inline
import nh3

ALLOWED_TAGS = {
    "p", "br", "hr", "span", "div",
    "strong", "b", "em", "i", "u",
    "a", "img",
    "ul", "ol", "li",
    "h1", "h2", "h3", "h4",
    "blockquote",
    "table", "thead", "tbody", "tr", "td", "th",
}

ALLOWED_ATTRIBUTES = {
    "*": {"style", "class"},
    "a": {"href", "title", "target"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan", "align", "valign"},
    "th": {"colspan", "rowspan", "align", "valign"},
}

BASE_EMAIL_CSS = """
p, li, td, th, blockquote {
    font-family: Arial, Helvetica, sans-serif;
    font-size: 15px;
    line-height: 1.6;
    color: #1f2937;
}
h1, h2, h3, h4 {
    font-family: Arial, Helvetica, sans-serif;
    color: #111827;
    margin: 0 0 12px 0;
}
h1 { font-size: 26px; }
h2 { font-size: 22px; }
h3 { font-size: 18px; }
h4 { font-size: 16px; }
p { margin: 0 0 14px 0; }
a { color: #007AFF; text-decoration: underline; }
ul, ol { margin: 0 0 14px 24px; padding: 0; }
blockquote {
    margin: 0 0 14px 0;
    padding: 8px 14px;
    border-left: 3px solid #d1d5db;
    color: #4b5563;
}
img { max-width: 100%; height: auto; }
hr { border: 0; border-top: 1px solid #e5e7eb; margin: 20px 0; }
"""


def sanitize_email_html(html):
    """Strip unsafe markup, keeping email-safe tags and the style attribute."""
    if not html:
        return ""
    return nh3.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES)


def inline_email_css(html):
    """Inline BASE_EMAIL_CSS so styling survives email clients."""
    if not html:
        return ""
    return css_inline.inline_fragment(html, BASE_EMAIL_CSS)
