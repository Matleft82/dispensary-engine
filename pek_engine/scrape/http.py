"""HTTP client for menu harvesting.

Prefers `curl_cffi` (browser TLS impersonation to pass anti-bot) and transparently
falls back to the stdlib `urllib` when it is not installed. A `FixtureClient` is
provided so adapter parsing can be unit-tested offline with recorded responses.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

try:  # optional, preferred
    from curl_cffi import requests as _cr  # type: ignore
    _HAS_CURL = True
except Exception:  # pragma: no cover - depends on environment
    _cr = None
    _HAS_CURL = False


_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


class HttpClient:
    """Thin GET/POST wrapper returning parsed JSON or raw text.

    Uses a *persistent* session so cookies (e.g. Cloudflare clearance from a
    `warm()` call) carry across requests — required by platforms like Dutchie.
    """

    def __init__(self, impersonate: str = "chrome", timeout: int = 60,
                 retries: int = 2, throttle: float = 0.2) -> None:
        self.impersonate = impersonate
        self.timeout = timeout
        self.retries = retries
        self.throttle = throttle
        self._session = None
        self._opener = None  # urllib fallback opener with a cookie jar

    @property
    def backend(self) -> str:
        return "curl_cffi" if _HAS_CURL else "urllib"

    def _curl_session(self):
        if self._session is None:
            self._session = _cr.Session(impersonate=self.impersonate)
        return self._session

    def _urllib_opener(self):
        if self._opener is None:
            import http.cookiejar
            jar = http.cookiejar.CookieJar()
            self._opener = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(jar))
        return self._opener

    def warm(self, url: str, headers=None) -> None:
        """Visit a page to collect cookies (Cloudflare clearance) before APIs."""
        try:
            self._request("GET", url, headers=headers)
        except Exception:
            pass

    def _request(self, method: str, url: str, params=None, headers=None,
                 json_body=None) -> tuple[int, str]:
        headers = {**_DEFAULT_HEADERS, **(headers or {})}
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                if _HAS_CURL:
                    sess = self._curl_session()
                    fn = sess.get if method == "GET" else sess.post
                    resp = fn(url, params=params, headers=headers,
                              json=json_body, timeout=self.timeout)
                    return resp.status_code, resp.text
                # urllib fallback (persistent cookie jar)
                full = url
                if params:
                    full = url + "?" + urllib.parse.urlencode(params, doseq=True)
                data = None
                if json_body is not None:
                    data = json.dumps(json_body).encode("utf-8")
                    headers = {**headers, "Content-Type": "application/json"}
                req = urllib.request.Request(full, data=data, headers=headers,
                                             method=method)
                with self._urllib_opener().open(req, timeout=self.timeout) as r:
                    return r.status, r.read().decode("utf-8", "replace")
            except Exception as exc:  # network error / anti-bot block
                last_exc = exc
                time.sleep(self.throttle * (attempt + 1))
        raise IOError(f"{method} {url} failed after {self.retries + 1} tries: {last_exc}")

    def get_json(self, url: str, params=None, headers=None) -> Any:
        time.sleep(self.throttle)
        status, text = self._request("GET", url, params=params, headers=headers)
        if status != 200:
            raise IOError(f"GET {url} -> HTTP {status}")
        return json.loads(text)

    def post_json(self, url: str, json_body=None, params=None, headers=None) -> Any:
        time.sleep(self.throttle)
        status, text = self._request("POST", url, params=params, headers=headers,
                                     json_body=json_body)
        if status != 200:
            raise IOError(f"POST {url} -> HTTP {status}")
        return json.loads(text)

    def get_text(self, url: str, params=None, headers=None) -> str:
        time.sleep(self.throttle)
        status, text = self._request("GET", url, params=params, headers=headers)
        if status != 200:
            raise IOError(f"GET {url} -> HTTP {status}")
        return text


class FixtureClient:
    """Offline client: returns recorded responses by URL substring.

    `mapping` is {url_substring: payload}. payload may be a dict/list (returned
    by get_json/post_json) or a str (returned by get_text). For paginated APIs
    return a list of payloads keyed by substring and they are served in order.
    """

    backend = "fixture"

    def __init__(self, mapping: dict[str, Any]) -> None:
        self._mapping = mapping
        self._cursor: dict[str, int] = {}

    def warm(self, url: str, headers=None) -> None:
        return None

    @classmethod
    def from_dir(cls, path: str | Path) -> "FixtureClient":
        mapping: dict[str, Any] = {}
        for fp in Path(path).glob("*.json"):
            mapping[fp.stem] = json.loads(fp.read_text())
        return cls(mapping)

    def _match(self, url: str):
        for key, payload in self._mapping.items():
            if key in url:
                if isinstance(payload, list) and payload and isinstance(payload[0], dict) \
                        and payload[0].get("__paged__"):
                    i = self._cursor.get(key, 0)
                    self._cursor[key] = i + 1
                    return payload[i] if i < len(payload) else {"__empty__": True}
                return payload
        raise KeyError(f"No fixture for url: {url}")

    def get_json(self, url: str, params=None, headers=None) -> Any:
        return self._match(url)

    def post_json(self, url: str, json_body=None, params=None, headers=None) -> Any:
        return self._match(url)

    def get_text(self, url: str, params=None, headers=None) -> str:
        m = self._match(url)
        return m if isinstance(m, str) else json.dumps(m)
