"""Small helpers shared by every module: time, hashing, slugs, domains and URLs."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, timezone
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text or "x"


def program_key(provider: str, name: str) -> str:
    return f"{slugify(provider)}:{slugify(name)}"


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_json(obj: Any) -> str:
    return sha256_text(canonical_json(obj))


def parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


# --- domains -----------------------------------------------------------------

# Public suffixes with two labels that we expect to meet (enough for this use;
# avoids a dependency on the full Public Suffix List).
_MULTI_PART_SUFFIXES = {
    "com.br", "net.br", "org.br", "gov.br", "co.uk", "org.uk", "ac.uk", "com.au",
    "co.jp", "co.in", "com.mx", "com.ar", "co.za", "com.cn", "com.sg", "co.kr",
    "com.tr", "com.co", "com.pe", "com.cl",
}

# Sites that can be *leads* for discovery but are never the official source of a
# program (unless the provider is the site itself, e.g. GitHub for Startups).
AGGREGATOR_DOMAINS = {
    "medium.com", "reddit.com", "linkedin.com", "x.com", "twitter.com", "facebook.com",
    "youtube.com", "substack.com", "producthunt.com", "github.io", "notion.site",
    "quora.com", "dev.to", "hackernoon.com", "techcrunch.com", "joinsecret.com",
    "f6s.com", "crunchbase.com", "wikipedia.org", "google.com.br", "bing.com",
}


def hostname(url: str) -> str:
    return (urlsplit(url or "").hostname or "").lower().strip(".")


def registrable_domain(host: str) -> str:
    host = (host or "").lower().strip(".")
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in _MULTI_PART_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def normalize_domain(domain: str) -> str:
    domain = (domain or "").strip().lower().strip(".")
    if "://" in domain:
        domain = hostname(domain)
    return domain.removeprefix("www.")


def host_in_domains(host: str, domains: Iterable[str]) -> bool:
    host = normalize_domain(host)
    for d in domains:
        d = normalize_domain(d)
        if d and (host == d or host.endswith("." + d)):
            return True
    return False


_TRACKING_PARAMS = re.compile(r"^(utm_|gclid$|fbclid$|ref$|mc_)")


def canonical_url(url: str) -> str:
    parts = urlsplit((url or "").strip())
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING_PARAMS.match(k)])
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, query, ""))


_NAME_STOPWORDS = {
    "for", "the", "program", "programme", "programa", "startup", "startups", "de", "para",
    "and", "e", "of", "do", "da", "credits", "creditos",
}


def name_tokens(name: str) -> set[str]:
    return {t for t in slugify(name).split("-") if t and t not in _NAME_STOPWORDS}


def similar_names(a: str, b: str, threshold: float = 0.6) -> bool:
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return slugify(a) == slugify(b)
    return len(ta & tb) / len(ta | tb) >= threshold


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n[...conteúdo truncado...]"
