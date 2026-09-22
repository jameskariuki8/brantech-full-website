"""Fetching a URL that a language model chose.

This is the only place in the codebase where a network destination is decided
by model output, and that makes it the one place where server-side request
forgery is a live concern rather than a checklist item. The application runs in
a compose network with `db`, `redis` and `cloudflared` addressable by name, on
a host that may expose a cloud metadata endpoint. A fetcher that resolves
whatever it is handed is a way to read all of that and hand it back as
"research".

So the rules are:

- **http and https only.** `file://` reads the filesystem, `gopher://` can be
  used to speak to Redis.
- **Public addresses only**, checked after DNS resolution rather than by
  pattern-matching the hostname. `localtest.me` resolves to 127.0.0.1 and looks
  nothing like localhost; an attacker-controlled domain can resolve to whatever
  it likes.
- **Redirects followed by hand**, each hop re-validated. Validating only the
  first URL is the classic bypass: the server answers 302 to
  http://169.254.169.254/ and requests follows it without asking again.
- **Bounded** in time, size and hops, because a model can be talked into
  fetching something enormous.

There is a residual DNS-rebinding window between the check and the connection.
Closing it properly means connecting to the validated IP and carrying the
hostname in the Host header, which breaks TLS verification unless the address
is threaded through the socket layer. It is documented here rather than
silently ignored, and the mitigation that matters more -- the egress rules on
the container -- belongs in the deployment.
"""
import ipaddress
import logging
import socket
from urllib.parse import urlsplit, urlunsplit

import requests

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = ("http", "https")
ALLOWED_CONTENT = ("text/html", "text/plain", "application/xhtml+xml",
                   "application/json", "text/markdown")

FETCH_TIMEOUT = 10          # seconds per hop
MAX_REDIRECTS = 3
MAX_BYTES = 2_000_000       # what we will read off the wire
MAX_CHARS = 20_000          # what we will hand to a model


class UnsafeURL(ValueError):
    """The URL is not one we are willing to fetch."""


def _addresses(host):
    """Every address `host` resolves to.

    All of them, not the first. A name with one public and one private A record
    is a way to pass a check that only looks at one.
    """
    try:
        info = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURL(f"could not resolve {host!r}: {exc}") from exc

    return {entry[4][0] for entry in info}


def _public(address):
    """True when `address` is a plain, routable, public address."""
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_multicast or ip.is_reserved or ip.is_unspecified
        # Explicit, because it is the specific target worth naming: the cloud
        # metadata endpoint is link-local and already covered above, but a
        # reader should see that it was considered.
        or address in ("169.254.169.254", "fd00:ec2::254")
    )


def validate(url):
    """Return `url` if it is safe to fetch, or raise `UnsafeURL`."""
    parts = urlsplit((url or "").strip())

    if parts.scheme not in ALLOWED_SCHEMES:
        raise UnsafeURL(
            f"only {' and '.join(ALLOWED_SCHEMES)} URLs may be fetched, got "
            f"{parts.scheme or 'no'} scheme"
        )

    if not parts.hostname:
        raise UnsafeURL("the URL has no host")

    # Credentials in a URL are a redirect-laundering trick and have no place in
    # something a model produced.
    if parts.username or parts.password:
        raise UnsafeURL("URLs with embedded credentials are refused")

    for address in _addresses(parts.hostname):
        if not _public(address):
            raise UnsafeURL(
                f"{parts.hostname} resolves to {address}, which is not a public address"
            )

    return urlunsplit(parts)


def fetch(url):
    """Fetch `url` and return (final_url, text).

    Raises `UnsafeURL` for anything refused and `requests.RequestException` for
    a transport failure. Neither is caught here: the tool wrapper turns them
    into something a model can read, and this function stays honest.
    """
    seen = []
    current = validate(url)

    for _ in range(MAX_REDIRECTS + 1):
        seen.append(current)

        response = requests.get(
            current,
            timeout=FETCH_TIMEOUT,
            stream=True,
            # Followed by hand so each hop is re-validated. This is the whole
            # reason redirects are not left to requests.
            allow_redirects=False,
            headers={
                "User-Agent": "TekloraNewsroom/1.0 (+https://teklora.co.ke)",
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9",
            },
        )

        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location", "")
            response.close()
            if not location:
                raise UnsafeURL(f"{current} redirected without a destination")

            current = validate(requests.compat.urljoin(current, location))
            if current in seen:
                raise UnsafeURL(f"redirect loop at {current}")
            continue

        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
        if content_type and content_type not in ALLOWED_CONTENT:
            response.close()
            raise UnsafeURL(f"{current} is {content_type}, which is not readable text")

        body = _read_capped(response)
        return current, extract_text(body, content_type)

    raise UnsafeURL(f"more than {MAX_REDIRECTS} redirects starting at {url}")


def _read_capped(response):
    """Read at most MAX_BYTES, whatever Content-Length claims.

    Streamed and counted rather than trusted, because the header is the
    server's word for it and this server was chosen by a model.
    """
    chunks, total = [], 0
    try:
        for chunk in response.iter_content(chunk_size=16_384):
            chunks.append(chunk)
            total += len(chunk)
            if total >= MAX_BYTES:
                logger.info("[fetch] truncating %s at %d bytes", response.url, total)
                break
    finally:
        response.close()

    raw = b"".join(chunks)[:MAX_BYTES]
    encoding = response.encoding or "utf-8"
    return raw.decode(encoding, errors="replace")


def extract_text(body, content_type=""):
    """Readable text from a fetched document.

    lxml rather than the regex in `messaging.rendering`, which strips tags but
    keeps what is inside them -- on a real web page that means the contents of
    every <script> and <style> block arrive as prose.
    """
    if content_type in ("text/plain", "text/markdown", "application/json"):
        return body[:MAX_CHARS]

    from lxml import html as lxml_html

    try:
        tree = lxml_html.fromstring(body)
    except Exception:  # noqa: BLE001 - malformed HTML is ordinary
        return body[:MAX_CHARS]

    for element in tree.xpath("//script | //style | //noscript | //template"):
        element.getparent().remove(element)

    text = tree.text_content()
    # Collapse the whitespace that markup leaves behind, without joining
    # paragraphs into one another.
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)[:MAX_CHARS]
