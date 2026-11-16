from datetime import date
from email.message import Message

import pytest

from credits_agent.applications import unsupported_tokens
from credits_agent.config import FetchConfig
from credits_agent.db import DuplicateApplication
from credits_agent.eligibility import History, evaluate
from credits_agent.fetcher import Fetcher, html_to_text
from credits_agent.profile import CompanyProfile
from credits_agent.util import canonical_url, host_in_domains, registrable_domain, similar_names

from .conftest import add_verified_program, make_details, verified

TODAY = date(2026, 11, 16)


# --- util ----------------------------------------------------------------------

def test_domains_and_urls():
    assert registrable_domain("mail.exemplo.com.br") == "exemplo.com.br"
    assert registrable_domain("aws.amazon.com") == "amazon.com"
    assert host_in_domains("www.aws.amazon.com", ["aws.amazon.com"])
    assert not host_in_domains("aws.amazon.com.evil.io", ["amazon.com"])
    assert canonical_url("https://www.Acme.com/startups/?utm_source=x&a=1#top") == "https://acme.com/startups?a=1"
    assert similar_names("AWS Activate", "AWS Activate Program")
    assert not similar_names("AWS Activate", "Google for Startups Cloud Program")


# --- fetcher -------------------------------------------------------------------

def test_html_to_text_drops_scripts_and_keeps_links():
    html = """<html><head><title>Startups</title><script>var x=1;</script></head>
      <body><h1>Program</h1><p>Get <b>$5,000</b> credits.</p>
      <a href="/apply">Apply now</a><a href="mailto:startups@acme.com">mail</a></body></html>"""
    title, text, links = html_to_text(html, "https://acme.com/startups")
    assert title == "Startups"
    assert "var x" not in text and "Get $5,000 credits." in text
    assert ("Apply now", "https://acme.com/apply") in links
    assert ("mailto", "mailto:startups@acme.com") in links


class _Resp:
    def __init__(self, url, status, body, ctype="text/html; charset=utf-8"):
        self.url, self.status, self.body = url, status, body
        self.headers = Message()
        self.headers["Content-Type"] = ctype

    def read(self, n=-1):
        return self.body

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Opener:
    def __init__(self, pages):
        self.pages, self.requested = pages, []

    def open(self, req, timeout=None):
        self.requested.append(req.full_url)
        status, body = self.pages.get(req.full_url, (404, b""))
        if status == 404:
            import urllib.error
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
        return _Resp(req.full_url, status, body)


def test_fetcher_respects_robots_txt():
    opener = _Opener({
        "https://acme.com/robots.txt": (200, b"User-agent: *\nDisallow: /private\n"),
        "https://acme.com/startups": (200, b"<p>ok page</p>"),
    })
    f = Fetcher(FetchConfig(delay_seconds=0), opener=opener)
    assert f.fetch("https://acme.com/startups").ok
    blocked = f.fetch("https://acme.com/private/form")
    assert blocked.robots_blocked and not blocked.ok
    assert "https://acme.com/private/form" not in opener.requested
    assert not f.fetch("http://acme.com/startups").ok  # https only


# --- profile / eligibility -----------------------------------------------------

def test_profile_uses_only_verified_fields(profile):
    assert profile.get("country") == "BR"
    assert profile.get("contact_email") is None  # present but not verified
    assert "contact_email" not in profile.verified_facts()
    assert ("contact_email", "não verificado") in profile.issues(TODAY)


def _eval(details, profile, history=None):
    return evaluate(details, profile, history or History(), TODAY, program_name="Acme Cloud for Startups",
                    provider="Acme")


def test_eligible(profile):
    assert _eval(make_details(), profile)["overall"] == "eligible"


def test_geography_exclusion_and_unknown(profile):
    r = _eval(make_details(geography__excluded_countries=["BR"]), profile)
    assert r["overall"] == "ineligible"
    no_country = CompanyProfile.from_dict({"country": {"value": "BR", "verified": False}})
    assert _eval(make_details(), no_country)["overall"] in ("needs_review", "ineligible")
    restricted = make_details(geography__scope="restricted", geography__allowed_countries=["US", "CA"],
                              geography__excluded_countries=[])
    assert _eval(restricted, profile)["overall"] == "ineligible"


def test_age_funding_deadline_and_backing(profile):
    assert _eval(make_details(eligibility__max_company_age_years=1), profile)["overall"] == "ineligible"
    assert _eval(make_details(eligibility__min_total_funding_usd=100000), profile)["overall"] == "ineligible"
    assert _eval(make_details(deadlines__application_deadline="2026-01-01"), profile)["overall"] == "ineligible"
    vc = make_details(eligibility__requires_vc_or_accelerator_backing=True)
    assert _eval(vc, profile)["overall"] == "ineligible"  # verified: no investors / accelerators
    backed = CompanyProfile.from_dict({**{k: verified(v.value) for k, v in profile.fields.items() if v.verified},
                                       "accelerators": verified(["Aceleradora X"])})
    assert _eval(vc, backed)["overall"] == "eligible"


def test_terms_block_duplicates_and_cooldown(profile):
    excl = make_details(terms__exclusive_with=["Acme Portfolio"])
    r = _eval(excl, profile, History(engaged_program_names=["Acme Portfolio Program"]))
    assert r["overall"] == "ineligible"
    assert _eval(make_details(), profile, History(self_credited=True))["overall"] == "ineligible"
    rejected = History(rejections=[date(2026, 10, 1)])
    assert _eval(make_details(), profile, rejected)["overall"] == "needs_review"  # cooldown unknown
    assert _eval(make_details(terms__reapply_cooldown_months=6), profile, rejected)["overall"] == "ineligible"
    assert _eval(make_details(terms__reapply_cooldown_months=1), profile, rejected)["overall"] == "eligible"


# --- db ------------------------------------------------------------------------

def test_one_active_application_per_program(db):
    p = add_verified_program(db)
    kw = dict(program_id=p["id"], packet={}, packet_hash="h", profile_hash="p", program_details_hash="d",
              missing=[], eligibility={})
    a1 = db.insert_application(status="draft", **kw)
    with pytest.raises(DuplicateApplication):
        db.insert_application(status="awaiting_approval", **kw)
    db.transition(a1, "draft", "rejected_by_user")
    db.insert_application(status="draft", **kw)  # terminal status frees the slot


def test_credit_balance_states(db):
    p = add_verified_program(db)
    c1 = db.insert_credit(provider="Acme", amount=1000, currency="usd", source="manual", program_id=p["id"],
                          expires_at="2099-01-01")
    c2 = db.insert_credit(provider="Acme", amount=50, currency="USD", source="manual", expires_at="2020-01-01")
    db.add_usage(c1, 250, "2026-11-10")
    rows = {r["id"]: r for r in db.credits_with_balance()}
    assert rows[c1]["remaining"] == 750 and rows[c1]["state"] == "partially_used" and rows[c1]["currency"] == "USD"
    assert rows[c2]["state"] == "expired"
    with pytest.raises(KeyError):
        db.add_usage(999, 1, "2026-11-10")


# --- grounding -----------------------------------------------------------------

def test_unsupported_tokens():
    assert unsupported_tokens("Founded on March 15, 2024", ["2024-03-15"]) == []
    assert unsupported_tokens("We raised US$ 250,000", [250000]) == []
    assert unsupported_tokens("We have 12 employees", [4]) == ["12"]
    assert unsupported_tokens("Mail ceo@exemplo.com.br", ["ceo@exemplo.com.br"]) == []
    assert unsupported_tokens("See https://other.io/x", ["https://exemplo.com.br"]) == ["https://other.io/x"]


def test_robots_unavailable_is_temporary():
    opener = _Opener({"https://acme.com/robots.txt": (503, b""), "https://acme.com/startups": (200, b"<p>x</p>")})
    f = Fetcher(FetchConfig(delay_seconds=0), opener=opener)
    r = f.fetch("https://acme.com/startups")
    assert not r.ok and not r.robots_blocked and "indisponível" in r.error
