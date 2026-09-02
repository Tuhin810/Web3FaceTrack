"""Hosting tests -- TASK.md 5.2 step 1, 3, 9."""

from __future__ import annotations

import httpx
import pytest

from facechain.config import Settings
from facechain.errors import HostingError
from facechain.hosting import HostedImage, upload_query_image

SAMPLE = b"not a real image, just bytes for a mocked upload"


class _Resp:
    def __init__(self, status=200, json_data=None, text=""):
        self.status_code = status
        self._json = json_data
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=self)

    def json(self):
        return self._json


# --- imgbb happy path and failures --------------------------------------------------


def test_imgbb_success(monkeypatch):
    def fake_post(url, **kwargs):
        assert url == "https://api.imgbb.com/1/upload"
        assert kwargs["params"]["key"] == "fake-imgbb-key"
        return _Resp(json_data={"success": True, "data": {"url": "https://i.ibb.co/x/q.png"}})

    monkeypatch.setattr(httpx, "post", fake_post)
    settings = Settings(imgbb_key="fake-imgbb-key")
    hosted = upload_query_image(SAMPLE, settings=settings)
    assert hosted == HostedImage(
        url="https://i.ibb.co/x/q.png", provider="imgbb", expires_hint="3600s"
    )


def test_imgbb_missing_key_falls_back_to_0x0(monkeypatch):
    def fake_post(url, **kwargs):
        assert url == "https://0x0.st"
        return _Resp(text="https://0x0.st/abcd.jpg\n")

    monkeypatch.setattr(httpx, "post", fake_post)
    settings = Settings(imgbb_key=None)
    hosted = upload_query_image(SAMPLE, settings=settings)
    assert hosted.provider == "0x0.st"
    assert hosted.url == "https://0x0.st/abcd.jpg"


def test_imgbb_rejection_falls_back_to_0x0(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        if "imgbb" in url:
            return _Resp(json_data={"success": False, "error": {"message": "bad key"}})
        return _Resp(text="https://0x0.st/fallback.jpg")

    monkeypatch.setattr(httpx, "post", fake_post)
    hosted = upload_query_image(SAMPLE, settings=Settings(imgbb_key="wrong"))
    assert hosted.provider == "0x0.st"
    assert calls == ["https://api.imgbb.com/1/upload", "https://0x0.st"]


def test_both_hosts_failing_raises_with_both_reasons(monkeypatch):
    def fake_post(url, **kwargs):
        return _Resp(status=500, text="server error")

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(HostingError) as exc:
        upload_query_image(SAMPLE, settings=Settings(imgbb_key="k"))
    assert "imgbb" in str(exc.value) and "0x0.st" in str(exc.value)


def test_0x0_rejects_non_url_response(monkeypatch):
    def fake_post(url, **kwargs):
        return _Resp(text="not a url")

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(HostingError, match="both image hosts failed"):
        upload_query_image(SAMPLE, settings=Settings(imgbb_key=None))


def test_upload_accepts_bytes_and_path(monkeypatch, tmp_path):
    seen = {}

    def fake_post(url, **kwargs):
        seen["data"] = kwargs["files"]["image"][1]
        return _Resp(json_data={"success": True, "data": {"url": "https://i.ibb.co/y/q.png"}})

    monkeypatch.setattr(httpx, "post", fake_post)
    f = tmp_path / "q.jpg"
    f.write_bytes(SAMPLE)
    upload_query_image(f, settings=Settings(imgbb_key="k"))
    assert seen["data"] == SAMPLE


def test_expiry_is_set_on_the_imgbb_request(monkeypatch):
    seen = {}

    def fake_post(url, **kwargs):
        seen["params"] = kwargs.get("params", {})
        return _Resp(json_data={"success": True, "data": {"url": "https://i.ibb.co/z/q.png"}})

    monkeypatch.setattr(httpx, "post", fake_post)
    upload_query_image(SAMPLE, settings=Settings(imgbb_key="k"))
    assert "expiration" in seen["params"]
    assert seen["params"]["expiration"] > 0


# --- real network, requires imgbb key --------------------------------------------------


@pytest.mark.network
def test_live_imgbb_upload_returns_a_fetchable_url(tmp_path):
    from pathlib import Path

    from facechain.config import get_settings

    if not get_settings().imgbb_key:
        pytest.skip("IMGBB_KEY not configured")

    image = Path("test.png")
    if not image.is_file():
        pytest.skip("test.png not present")

    hosted = upload_query_image(image)
    assert hosted.provider == "imgbb"
    resp = httpx.get(hosted.url, timeout=15)
    assert resp.status_code == 200
