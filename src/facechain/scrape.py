"""Stage 2 page fetching -- TASK.md 5.2 step 4.

Every fetch here is defensive by design, because the input is 15 arbitrary URLs picked
by a third-party search index, not URLs this codebase controls:

- robots.txt is honoured, but its response is validated as text before being parsed --
  an image CDN was found (during Phase 6 recon) serving *every* path, robots.txt
  included, as an image with HTTP 200 (DECISIONS.md D15). Feeding that to a robots
  parser would silently derive nonsense rules.
- Rate limiting is 1 request/sec **per domain**, shared across the robots.txt fetch,
  the page fetch, and every image fetch from that domain -- so hammering a host with
  its own robots.txt request doesn't count as a free pass.
- Failures are collected, not raised: a candidate page that fails to fetch is logged
  and skipped by the matcher, not a reason to abort the run.
"""

from __future__ import annotations

import io
import logging
import threading
import time
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Self
from urllib.parse import urljoin, urlparse

import httpx
from PIL import Image
from selectolax.parser import HTMLParser

from .errors import ScrapeError

log = logging.getLogger(__name__)

USER_AGENT = "facechain-verify/0.1.0 (+https://github.com/OWNER/facechain-verify)"
REQUEST_TIMEOUT = 10.0
RETRIES = 2
BACKOFF_BASE = 1.0  # seconds; attempt N waits BACKOFF_BASE * 2**(N-1)
RATE_LIMIT_SECONDS = 1.0
MIN_IMAGE_DIMENSION = 200
MAX_IMAGES_PER_PAGE = 5
TEXT_EXCERPT_CHARS = 2000


@dataclass(frozen=True)
class ScrapedPage:
    url: str
    title: str | None
    og_title: str | None
    og_image: str | None
    og_description: str | None
    text_excerpt: str
    image_urls: list[str]  # candidates, largest-known-first, capped at MAX_IMAGES_PER_PAGE
    fetched_at: str


class _DomainRateLimiter:
    """1 request/sec per host, shared across robots.txt, the page, and its images."""

    def __init__(self, min_interval: float = RATE_LIMIT_SECONDS):
        self._min_interval = min_interval
        self._last_request: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        with self._lock:
            now = time.monotonic()
            last = self._last_request.get(host)
            delay = 0.0 if last is None else max(0.0, self._min_interval - (now - last))
            self._last_request[host] = now + delay
        if delay > 0:
            time.sleep(delay)


class Scraper:
    """Holds rate-limit and robots.txt state across a batch of candidate fetches --
    construct one per pipeline run, not one per page, so the per-domain budget and the
    robots cache are actually shared.
    """

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT, follow_redirects=True
        )
        self._owns_client = client is None
        self._rate_limiter = _DomainRateLimiter()
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- robots.txt ------------------------------------------------------------------

    def _robots_for(self, host: str, scheme: str) -> urllib.robotparser.RobotFileParser | None:
        """None means "no usable robots.txt" -- treated as allow-all, per the
        RFC 9309 convention of failing open on a missing or unreadable robots file.
        """
        if host in self._robots_cache:
            return self._robots_cache[host]

        robots_url = f"{scheme}://{host}/robots.txt"
        parser: urllib.robotparser.RobotFileParser | None = None
        try:
            resp = self._get(robots_url, host)
        except ScrapeError:
            resp = None

        if resp is not None and resp.status_code == 200:
            content_type = resp.headers.get("content-type", "")
            if content_type.split(";")[0].strip().startswith("text/"):
                parser = urllib.robotparser.RobotFileParser()
                parser.parse(resp.text.splitlines())
            else:
                log.warning(
                    "robots.txt at %s served as %r, not text -- treating as absent "
                    "(DECISIONS.md D15)",
                    robots_url,
                    content_type,
                )

        self._robots_cache[host] = parser
        return parser

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        parser = self._robots_for(parsed.netloc, parsed.scheme or "https")
        if parser is None:
            return True
        return parser.can_fetch(USER_AGENT, url)

    # --- rate-limited, retried HTTP ---------------------------------------------------

    def _get(self, url: str, host: str) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(RETRIES + 1):
            self._rate_limiter.wait(host)
            try:
                resp = self._client.get(url)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"{resp.status_code}", request=resp.request, response=resp
                    )
                return resp
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if attempt < RETRIES:
                    time.sleep(BACKOFF_BASE * (2**attempt))
        raise ScrapeError(f"failed to fetch {url} after {RETRIES + 1} attempts: {last_exc}")

    # --- page fetch + extraction -------------------------------------------------------

    def fetch_page(self, url: str) -> ScrapedPage:
        parsed = urlparse(url)
        if not self.allowed(url):
            raise ScrapeError(f"disallowed by robots.txt: {url}")

        resp = self._get(url, parsed.netloc)
        if resp.status_code != 200:
            # 4xx not covered by _get's retry (429/5xx only -- those are treated as
            # possibly transient). A block page or 404 must not be parsed as content:
            # its content-type is very often still text/html, so without this check
            # an error page would silently be scraped as if it had succeeded (found
            # scraping real candidates in Phase 7 dev -- wdwnt.com and ebay.com both
            # served a 403 with an HTML body).
            raise ScrapeError(f"{url} returned HTTP {resp.status_code}")
        content_type = resp.headers.get("content-type", "")
        if not content_type.split(";")[0].strip().startswith("text/html"):
            raise ScrapeError(f"{url} is not HTML (content-type: {content_type!r})")

        tree = HTMLParser(resp.text)

        def meta(prop: str) -> str | None:
            node = tree.css_first(f'meta[property="{prop}"]') or tree.css_first(
                f'meta[name="{prop}"]'
            )
            return node.attributes.get("content") if node else None

        title_node = tree.css_first("title")
        text = tree.body.text(separator=" ", strip=True) if tree.body else ""

        image_urls = self._extract_image_urls(tree, url)

        return ScrapedPage(
            url=url,
            title=title_node.text(strip=True) if title_node else None,
            og_title=meta("og:title"),
            og_image=meta("og:image"),
            og_description=meta("og:description"),
            text_excerpt=text[:TEXT_EXCERPT_CHARS],
            image_urls=image_urls,
            fetched_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    def _extract_image_urls(self, tree: HTMLParser, base_url: str) -> list[str]:
        """og:image first (it's the page's own chosen representative image, and
        TASK.md 5.2 lists it as a distinct extraction target), then <img> tags with
        HTML-declared dimensions at or above the floor, largest first. Real pixel
        dimensions are only known once an image is actually downloaded -- this is a
        pre-filter, not the final word (fetch_images_for_faces re-checks after decode).
        """
        seen: set[str] = set()
        sized: list[tuple[int, str]] = []

        og = tree.css_first('meta[property="og:image"]')
        if og and og.attributes.get("content"):
            url = urljoin(base_url, og.attributes["content"])
            seen.add(url)
            sized.append((10**9, url))  # og:image sorts first, unconditionally

        for img in tree.css("img[src]"):
            src = img.attributes.get("src")
            if not src:
                continue
            url = urljoin(base_url, src)
            if url in seen or not url.startswith(("http://", "https://")):
                continue

            width = _int_attr(img.attributes.get("width"))
            height = _int_attr(img.attributes.get("height"))
            if width is not None and height is not None:
                if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
                    continue
                size = width * height
            else:
                size = -1  # unknown size: kept, but sorted after every known-large image

            seen.add(url)
            sized.append((size, url))

        sized.sort(key=lambda pair: pair[0], reverse=True)
        return [url for _, url in sized[:MAX_IMAGES_PER_PAGE]]

    # --- image fetch for face re-verification ------------------------------------------

    def fetch_image_bytes(self, url: str) -> bytes:
        """Raw bytes only -- never written to disk. TASK.md 2.1: third-party images
        fetched during re-verification are held in memory and discarded after
        comparison.
        """
        parsed = urlparse(url)
        resp = self._get(url, parsed.netloc)
        if resp.status_code != 200:
            raise ScrapeError(f"{url} returned HTTP {resp.status_code}")
        content_type = resp.headers.get("content-type", "")
        if not content_type.split(";")[0].strip().startswith("image/"):
            raise ScrapeError(f"{url} is not an image (content-type: {content_type!r})")
        return resp.content


def _int_attr(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(float(value))  # some pages use "200.0" or similar
    except ValueError:
        return None


def image_meets_min_dimension(data: bytes) -> bool:
    """Real pixel check after download -- HTML width/height attributes can lie or omit."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            return im.width >= MIN_IMAGE_DIMENSION and im.height >= MIN_IMAGE_DIMENSION
    except Exception:  # noqa: BLE001 -- Pillow raises many types for a bad image;
        # any failure to decode simply means "this is not a usable image".
        return False
