import re


def render_subject(subject, name):
    return (subject or "").replace("{{ name }}", name or "").replace("{{name}}", name or "")


def render_body(body_html, name, unsubscribe_url):
    out = body_html or ""
    for token, value in (
        ("{{ name }}", name or ""),
        ("{{name}}", name or ""),
        ("{{ unsubscribe_url }}", unsubscribe_url or ""),
        ("{{unsubscribe_url}}", unsubscribe_url or ""),
    ):
        out = out.replace(token, value)
    return out


def html_to_text(html):
    text = re.sub(r"<[^>]+>", "", html or "")
    return re.sub(r"[ \t]+", " ", text)
