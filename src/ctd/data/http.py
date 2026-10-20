"""HTTP (and anonymous FTP) access for fetchers: one small interface so tests can substitute a fake."""

import time
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# FRED stalls (read timeout) on some user agents, e.g. ones containing "collector"; this one is accepted.
USER_AGENT = "Mozilla/5.0 (compatible; ctd-eod-fetcher/0.1)"


class FetchError(Exception):
    """A source returned nothing usable; nothing is stored for it."""


@dataclass(frozen=True)
class Response:
    url: str
    status: int
    content: bytes
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", self.headers.get("Content-Type", ""))

    def ensure_ok(self) -> "Response":
        if self.status != 200:
            raise FetchError(f"HTTP {self.status} from {self.url}")
        return self


class Http(Protocol):
    def get(self, url: str, params: dict | None = None, headers: dict | None = None) -> Response: ...

    def post(self, url: str, data: dict | None = None, headers: dict | None = None) -> Response: ...


class RequestsHttp:
    """``requests`` session with retries on transient errors and a polite delay between calls."""

    def __init__(self, timeout: float = 180, delay: float = 0.5, retries: int = 3):
        self.timeout = timeout
        self.delay = delay
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        retry = Retry(total=retries, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=None)
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self._last = 0.0

    def _wait(self) -> None:
        pause = self._last + self.delay - time.monotonic()
        if pause > 0:
            time.sleep(pause)
        self._last = time.monotonic()

    def _wrap(self, r: requests.Response) -> Response:
        return Response(r.url, r.status_code, r.content, dict(r.headers))

    def get(self, url, params=None, headers=None) -> Response:
        self._wait()
        if url.startswith("ftp://"):  # anonymous FTP; a missing file raises URLError
            with urllib.request.urlopen(url, timeout=self.timeout) as r:
                return Response(url, 200, r.read())
        return self._wrap(self.session.get(url, params=params, headers=headers, timeout=self.timeout))

    def post(self, url, data=None, headers=None) -> Response:
        self._wait()
        return self._wrap(self.session.post(url, data=data, headers=headers, timeout=self.timeout))
