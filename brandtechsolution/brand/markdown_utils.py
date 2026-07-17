"""Render user-authored Markdown to sanitized HTML safe for direct output."""
import markdown as _markdown
import nh3

_ALLOWED_TAGS = {
    "p", "br", "h1", "h2", "h3", "h4", "strong", "em", "b", "i",
    "ul", "ol", "li", "a", "code", "pre", "blockquote", "hr", "img",
    "table", "thead", "tbody", "tr", "th", "td",
}

_ALLOWED_ATTRIBUTES = {
    "a": {"href", "title", "rel"},
    "img": {"src", "alt", "title"},
}


def render_markdown(text: str) -> str:
    """Convert Markdown text to sanitized HTML.

    Single newlines become <br> (nl2br) so legacy plain-text posts keep their
    line breaks. Output is sanitized against an allowlist, so raw HTML such as
    <script> or event-handler attributes is stripped.
    """
    if not text:
        return ""
    html = _markdown.markdown(text, extensions=["extra", "nl2br", "sane_lists"])
    return nh3.clean(html, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRIBUTES, link_rel=None)
