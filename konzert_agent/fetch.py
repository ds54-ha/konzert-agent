"""HTTP-Abruf mit robots.txt-Prüfung und höflicher Pause pro Host."""
from __future__ import annotations

import logging
import threading
import time
from urllib import robotparser
from urllib.parse import urlsplit

import requests

log = logging.getLogger(__name__)


class RobotsDisallowed(Exception):
    pass


class Fetcher:
    def __init__(self, user_agent: str, delay: float = 2.0, respect_robots: bool = True, timeout: float = 25):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept-Language": "de-CH,de;q=0.9,en;q=0.7",
        })
        self.user_agent = user_agent
        self.delay = delay
        self.respect_robots = respect_robots
        self.timeout = timeout
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self._last_hit: dict[str, float] = {}
        self._lock = threading.Lock()

    def _robots_for(self, url: str) -> robotparser.RobotFileParser | None:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                r = self.session.get(base + "/robots.txt", timeout=self.timeout)
                if r.status_code >= 400:
                    rp = None          # keine robots.txt -> alles erlaubt
                else:
                    rp.parse(r.text.splitlines())
            except requests.RequestException as e:
                log.warning("robots.txt für %s nicht lesbar (%s) – fahre fort", base, e)
                rp = None
            self._robots[base] = rp
        return self._robots[base]

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        rp = self._robots_for(url)
        return True if rp is None else rp.can_fetch(self.user_agent, url)

    def _throttle(self, host: str):
        with self._lock:
            wait = self._last_hit.get(host, 0) + self.delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_hit[host] = time.monotonic()

    def get(self, url: str) -> str:
        return self._request("GET", url)

    def post(self, url: str, data: dict, headers: dict | None = None) -> str:
        """Für «mehr laden»-Knöpfe, die per POST nachladen (Cookies der Sitzung bleiben erhalten)."""
        return self._request("POST", url, data=data, headers=headers)

    def _request(self, method: str, url: str, **kw) -> str:
        if not self.allowed(url):
            raise RobotsDisallowed(f"robots.txt verbietet {url}")
        self._throttle(urlsplit(url).netloc)
        r = self.session.request(method, url, timeout=self.timeout, **kw)
        r.raise_for_status()
        if not r.encoding or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding
        return r.text
