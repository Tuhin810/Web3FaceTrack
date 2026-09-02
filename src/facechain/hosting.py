"""Image hosting -- TASK.md 5.2 step 1, 3 (imgbb primary), 9 (0x0.st fallback).

Reverse image search needs a URL the provider's crawler can fetch, so the query image
has to go somewhere public first. imgbb is primary because it supports an explicit
expiry, so the upload does not outlive the run that needed it; 0x0.st is the fallback
when imgbb is unreachable or unconfigured.

Every upload is logged (TASK.md 5.2 step 1: "Log the URL") since it is the one point in
the pipeline where the subject's photo leaves local control, and that deserves a visible
audit trail, not just a returned string.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from .config import Settings, get_settings
from .errors import ConfigError, HostingError

log = logging.getLogger(__name__)

USER_AGENT = "facechain-verify/0.1.0 (+https://github.com/OWNER/facechain-verify)"
DEFAULT_TIMEOUT = 15.0
# imgbb's own maximum is 15552000s (180 days); an hour is plenty for a single run and
# keeps the query photo from lingering in public longer than the demo needs it to.
IMGBB_EXPIRY_SECONDS = 3600


@dataclass(frozen=True)
class HostedImage:
    url: str
    provider: str  # "imgbb" | "0x0.st"
    expires_hint: str | None  # human-readable, provider-specific; not guaranteed exact


def _read_bytes(image: bytes | str | Path) -> bytes:
    if isinstance(image, (str, Path)):
        return Path(image).read_bytes()
    return image


def _upload_imgbb(data: bytes, settings: Settings) -> HostedImage:
    try:
        key = settings.require("imgbb_key", "host the query image via imgbb")
    except ConfigError as exc:
        raise HostingError(str(exc)) from exc
    try:
        resp = httpx.post(
            "https://api.imgbb.com/1/upload",
            params={"key": key, "expiration": IMGBB_EXPIRY_SECONDS},
            files={"image": ("query.jpg", data)},
            headers={"User-Agent": USER_AGENT},
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
    except httpx.HTTPError as exc:
        raise HostingError(f"imgbb upload failed: {exc}") from exc

    if not payload.get("success"):
        raise HostingError(f"imgbb rejected the upload: {payload}")

    url = payload["data"]["url"]
    return HostedImage(url=url, provider="imgbb", expires_hint=f"{IMGBB_EXPIRY_SECONDS}s")


def _upload_0x0(data: bytes, settings: Settings) -> HostedImage:
    try:
        resp = httpx.post(
            "https://0x0.st",
            files={"file": ("query.jpg", data)},
            headers={"User-Agent": USER_AGENT},
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HostingError(f"0x0.st upload failed: {exc}") from exc

    url = resp.text.strip()
    if not url.startswith("http"):
        raise HostingError(f"0x0.st returned an unexpected response: {resp.text!r}")
    return HostedImage(url=url, provider="0x0.st", expires_hint="~30-365 days, usage-dependent")


def upload_query_image(
    image: bytes | str | Path, settings: Settings | None = None
) -> HostedImage:
    """Upload the query image and return its public URL.

    Tries imgbb first, falls back to 0x0.st on any failure -- including a missing
    IMGBB_KEY, so this still works with only the fallback configured.
    """
    settings = settings or get_settings()
    data = _read_bytes(image)

    try:
        hosted = _upload_imgbb(data, settings)
    except HostingError as primary_exc:
        log.warning("imgbb upload failed (%s); falling back to 0x0.st", primary_exc)
        try:
            hosted = _upload_0x0(data, settings)
        except HostingError as fallback_exc:
            raise HostingError(
                f"both image hosts failed. imgbb: {primary_exc}. 0x0.st: {fallback_exc}"
            ) from fallback_exc

    log.info("hosted query image at %s (%s, expires ~%s)",
              hosted.url, hosted.provider, hosted.expires_hint)
    return hosted
