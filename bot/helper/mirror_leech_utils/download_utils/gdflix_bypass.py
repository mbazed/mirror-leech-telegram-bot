"""Cloudflare-aware gdflix resolver.

gdflix fronts its file pages with an anti-bot layer that rejects plain
requests and legacy cloudscraper. curl_cffi's browser impersonation is
required because the edge fingerprints TLS/JA3 and HTTP/2 settings.

Resolution order:
    1. GET the gdflix URL with a Chrome impersonation session.
    2. If the page exposes an "instant" download link, resolve it through
       the xtrocdn API.
    3. Otherwise perform the classic sharer multipart POST to obtain the
       drive URL.
    4. Follow the returned URL and extract a drive.google.com or
       drive.usercontent.google.com link from the landing page.
"""

from __future__ import annotations

from re import findall, search
from urllib.parse import parse_qs, urljoin, urlparse
from uuid import uuid4

from curl_cffi import requests as cffi_requests

from ...ext_utils.exceptions import DirectDownloadLinkException

_DRIVE_HOSTS = (
    "drive.google.com",
    "drive.usercontent.google.com",
    "docs.google.com",
)
_INSTANT_API = "https://xtrocdn.zencloud.lol/api"
_WORKER_URL_PATTERN = r"let worker_url\s*=\s*['\"]([^'\"]+)['\"]"


def _is_drive_url(url: str) -> bool:
    if url.startswith("//"):
        url = f"https:{url}"
    host = (urlparse(url).hostname or "").lower()
    return any(host == drive or host.endswith(f".{drive}") for drive in _DRIVE_HOSTS)


def _extract_drive_from_html(html: str, base_url: str | None = None) -> str:
    for href in findall(r'href=["\']([^"\']+)["\']', html):
        if base_url:
            href = urljoin(base_url, href)
        if _is_drive_url(href):
            return href
    return ""


def _extract_key(html: str) -> str:
    if m := findall(r'"key"\s*[:,]\s*"(.*?)"', html):
        return m[0]
    if m := search(r'name=["\']key["\'][^>]*value=["\']([^"\']+)', html):
        return m.group(1)
    return ""


def _instant_key(html: str) -> str:
    for href in findall(r'href=["\']([^"\']+)["\']', html):
        if "instant" in href.lower() or "zencloud" in href.lower():
            query = parse_qs(urlparse(href).query)
            for name in ("keys", "key", "token"):
                if query.get(name):
                    return query[name][0]
    return ""


def _post_instant(session, page_url: str, key: str) -> str:
    parsed = urlparse(page_url)
    response = session.post(
        _INSTANT_API,
        data={"keys": key},
        headers={
            "Referer": page_url,
            "Origin": f"{parsed.scheme}://{parsed.netloc}",
        },
    )
    if response.status_code in (403, 429):
        raise DirectDownloadLinkException(
            f"ERROR: gdflix instant API blocked the request (HTTP {response.status_code})"
        )
    try:
        return response.json().get("url", "")
    except ValueError:
        return ""


def _post_direct(session, page_url: str, key: str) -> str:
    parsed = urlparse(page_url)
    hostname = parsed.hostname or ""
    boundary = uuid4()
    body = (
        f"------WebKitFormBoundary{boundary}\r\n"
        'Content-Disposition: form-data; name="action"\r\n\r\n'
        "direct\r\n"
        f"------WebKitFormBoundary{boundary}\r\n"
        'Content-Disposition: form-data; name="key"\r\n\r\n'
        f"{key}\r\n"
        f"------WebKitFormBoundary{boundary}\r\n"
        'Content-Disposition: form-data; name="action_token"\r\n\r\n'
        "\r\n"
        f"------WebKitFormBoundary{boundary}--\r\n"
    )
    response = session.post(
        page_url,
        data=body.encode("utf-8"),
        headers={
            "Content-Type": f"multipart/form-data; boundary=----WebKitFormBoundary{boundary}",
            "x-token": hostname,
            "Referer": page_url,
            "Origin": f"{parsed.scheme}://{parsed.netloc}",
        },
    )
    if response.status_code in (403, 429):
        raise DirectDownloadLinkException(
            f"ERROR: gdflix blocked the direct request (HTTP {response.status_code})"
        )
    try:
        return response.json().get("url", "")
    except ValueError:
        return ""


def _resolve_candidate(session, page_url: str, candidate: str) -> str:
    if not candidate:
        return ""
    if _is_drive_url(candidate):
        return candidate

    try:
        response = session.get(candidate, headers={"Referer": page_url})
        if drive := _extract_drive_from_html(response.text, str(response.url)):
            return drive
        if worker := search(_WORKER_URL_PATTERN, response.text):
            worker_url = worker.group(1)
            if _is_drive_url(worker_url):
                return worker_url
            redirect = session.get(
                worker_url,
                headers={"Referer": str(response.url)},
                allow_redirects=False,
            )
            if _is_drive_url(redirect.headers.get("Location", "")):
                return redirect.headers["Location"]
    except DirectDownloadLinkException:
        raise
    except Exception:
        pass

    return candidate


def gdflix_bypass(url: str) -> str:
    """Resolve a gdflix URL to its underlying Google Drive URL."""
    try:
        with cffi_requests.Session(impersonate="chrome136", timeout=30) as session:
            response = session.get(url, allow_redirects=True)
            if response.status_code in (403, 429):
                raise DirectDownloadLinkException(
                    f"ERROR: gdflix blocked the request (HTTP {response.status_code})"
                )

            page_url = str(response.url)
            html = response.text

            if drive := _extract_drive_from_html(html, page_url):
                return drive

            if instant_key := _instant_key(html):
                try:
                    candidate = _post_instant(session, page_url, instant_key)
                    if resolved := _resolve_candidate(session, page_url, candidate):
                        if _is_drive_url(resolved):
                            return resolved
                except DirectDownloadLinkException:
                    pass

            key = _extract_key(html)
            if not key:
                raise DirectDownloadLinkException("ERROR: gdflix key not found")

            candidate = _post_direct(session, page_url, key)
            if not candidate:
                raise DirectDownloadLinkException(
                    "ERROR: gdflix did not return a direct URL"
                )

            resolved = _resolve_candidate(session, page_url, candidate)
            if _is_drive_url(resolved):
                return resolved
            raise DirectDownloadLinkException(
                "ERROR: gdflix resolved URL is not a Google Drive link"
            )
    except DirectDownloadLinkException:
        raise
    except Exception as e:
        raise DirectDownloadLinkException(f"ERROR: gdflix bypass failed: {e}") from e
