"""Polite page fetcher: honours robots.txt, rate-limits per host, never logs in,
never submits forms. Converts HTML to plain text and keeps the page's links so
the model can find the application / terms URLs."""
from __future__ import annotations

import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .config import FetchConfig
from .util import sha256_text

_SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "iframe", "canvas"}
_BLOCK_TAGS = {
    "p", "div", "section", "article", "header", "footer", "li", "ul", "ol", "tr", "table",
    "h1", "h2", "h3", "h4", "h5", "h6", "br", "hr", "main", "aside", "nav", "dd", "dt", "summary",
}


class _TextExtractor(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.title = ""
        self._skip = 0
        self._in_title = False
        self._href: str | None = None
        self._anchor: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "a":
            href = dict(attrs).get("href")
            if href and not href.startswith(("javascript:", "#", "mailto:")):
                self._href = urljoin(self.base_url, href)
                self._anchor = []
            elif href and href.startswith("mailto:"):
                self.links.append(("mailto", href))
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag == "a" and self._href:
            self.links.append((" ".join("".join(self._anchor).split()), self._href))
            self._href = None
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
            return
        self.parts.append(data)
        if self._href is not None:
            self._anchor.append(data)

    def text(self) -> str:
        lines = (" ".join(line.split()) for line in "".join(self.parts).splitlines())
        out: list[str] = []
        for line in lines:
            if line and (not out or out[-1] != line):
                out.append(line)
        return "\n".join(out)


def html_to_text(html: str, base_url: str) -> tuple[str, str, list[tuple[str, str]]]:
    parser = _TextExtractor(base_url)
    parser.feed(html)
    parser.close()
    seen: set[str] = set()
    links = []
    for text, href in parser.links:
        if href not in seen:
            seen.add(href)
            links.append((text, href))
    return " ".join(parser.title.split()), parser.text(), links


@dataclass
class FetchResult:
    url: str
    final_url: str = ""
    status: int = 0
    title: str = ""
    text: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)
    error: str = ""
    robots_blocked: bool = False

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300 and not self.error and not self.robots_blocked

    @property
    def content_hash(self) -> str:
        return sha256_text(self.text)

    def for_llm(self, limit: int) -> str:
        link_lines = "\n".join(f"- [{t or 'link'}] {h}" for t, h in self.links[:250])
        body = self.text if len(self.text) <= limit else self.text[:limit] + "\n[...truncado...]"
        return f"URL: {self.final_url or self.url}\nTITLE: {self.title}\n\nPAGE TEXT:\n{body}\n\nLINKS:\n{link_lines}"


class Fetcher:
    def __init__(self, cfg: FetchConfig, opener: urllib.request.OpenerDirector | None = None,
                 sleep=time.sleep, clock=time.monotonic):
        self.cfg = cfg
        self.opener = opener or urllib.request.build_opener()
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._last_hit: dict[str, float] = {}
        self._sleep = sleep
        self._clock = clock

    def _throttle(self, host: str) -> None:
        last = self._last_hit.get(host)
        if last is not None:
            wait = self.cfg.delay_seconds - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_hit[host] = self._clock()

    def _get(self, url: str) -> tuple[int, str, bytes, str]:
        req = urllib.request.Request(url, headers={
            "User-Agent": self.cfg.user_agent,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
            "Accept-Language": "en,pt-BR;q=0.8",
        })
        self._throttle(urlsplit(url).netloc)
        try:
            with self.opener.open(req, timeout=self.cfg.timeout_seconds) as resp:
                body = resp.read(self.cfg.max_bytes + 1)
                charset = resp.headers.get_content_charset() or "utf-8"
                ctype = resp.headers.get_content_type() or ""
                return resp.status, resp.geturl(), body, f"{ctype};{charset}"
        except urllib.error.HTTPError as exc:
            return exc.code, url, b"", ""

    def robots(self, url: str) -> str:
        """'allowed', 'disallowed' or 'unavailable' (robots.txt temporarily unreachable)."""
        parts = urlsplit(url)
        root = f"{parts.scheme}://{parts.netloc}"
        rp = self._robots.get(root)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            try:
                status, _, body, ctype = self._get(root + "/robots.txt")
            except (urllib.error.URLError, OSError, ValueError):
                return "unavailable"  # not cached: retried on the next request
            if status >= 500 or status == 429:
                return "unavailable"
            if status in (401, 403):
                rp.disallow_all = True
            elif 200 <= status < 300:
                rp.parse(body.decode(ctype.split(";")[-1] or "utf-8", errors="replace").splitlines())
            else:
                rp.allow_all = True  # no robots.txt = no restriction declared
            self._robots[root] = rp
        return "allowed" if rp.can_fetch(self.cfg.user_agent, url) else "disallowed"

    def fetch(self, url: str) -> FetchResult:
        result = FetchResult(url=url)
        if urlsplit(url).scheme != "https":
            result.error = "somente URLs https são aceitas"
            return result
        robots = self.robots(url)
        if robots == "disallowed":
            result.robots_blocked = True
            result.error = "bloqueado por robots.txt"
            return result
        if robots == "unavailable":
            result.error = "robots.txt indisponível no momento; tentarei de novo"
            return result
        try:
            status, final_url, body, ctype = self._get(url)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            result.error = f"falha de rede: {exc}"
            return result
        result.status, result.final_url = status, final_url
        if not 200 <= status < 300:
            result.error = f"HTTP {status}"
            return result
        if len(body) > self.cfg.max_bytes:
            body = body[: self.cfg.max_bytes]
        content_type, _, charset = ctype.partition(";")
        decoded = body.decode(charset or "utf-8", errors="replace")
        if "html" in content_type or decoded.lstrip()[:1] == "<":
            result.title, result.text, result.links = html_to_text(decoded, final_url)
        elif content_type.startswith("text/"):
            result.text = decoded
        else:
            result.error = f"tipo de conteúdo não suportado: {content_type}"
        return result
