import copy
from pathlib import Path

import pytest

from credits_agent.config import Config
from credits_agent.db import Database
from credits_agent.fetcher import FetchResult
from credits_agent.profile import CompanyProfile
from credits_agent.schemas import validate

PAGE_TEXT = (
    "Acme Cloud for Startups. Eligible startups receive up to $25,000 in Acme Cloud credits. "
    "Credits are valid for 12 months. The program is open to startups worldwide, except in Cuba. "
    "Companies must be less than 5 years old and have raised less than $5M. "
    "Apply through the online form. One application per company. "
) * 20


def make_details(**overrides) -> dict:
    d = {
        "is_program_page": True,
        "published_by_provider": True,
        "provider": "Acme",
        "program_name": "Acme Cloud for Startups",
        "category": "cloud",
        "summary_pt": "Programa de créditos de nuvem da Acme.",
        "program_status": "open",
        "official_domains": ["acme.com"],
        "benefit": {"benefit_type": "cloud_credits", "max_value": 25000, "currency": "USD",
                    "value_description": "até US$ 25.000 em créditos", "credit_validity_months": 12, "tiers": []},
        "eligibility": {"stages_allowed": [], "max_company_age_years": 5, "max_total_funding_usd": 5_000_000,
                        "min_total_funding_usd": None, "max_annual_revenue_usd": None,
                        "requires_incorporation": True, "requires_vc_or_accelerator_backing": None,
                        "requires_partner_referral_code": None, "requires_new_customer": None,
                        "requires_company_email_domain": None, "requires_public_website": None,
                        "other_requirements": []},
        "geography": {"scope": "worldwide", "allowed_countries": [], "excluded_countries": ["CU"], "notes": ""},
        "deadlines": {"application_deadline": "", "rolling": True, "notes": ""},
        "application": {"method": "web_form", "url": "https://acme.com/startups/apply", "email_address": "",
                        "requires_account_login": True,
                        "required_fields": ["Company name", "Website", "Founded", "Total funding (USD)"],
                        "required_documents": []},
        "terms": {"terms_url": "", "one_per_company": True, "exclusive_with": [], "reapply_cooldown_months": None,
                  "prohibited_practices": [], "automation_prohibited": None, "notes": ""},
        "evidence": [{"claim": "value", "quote": "receive up to $25,000 in Acme Cloud credits"},
                     {"claim": "geo", "quote": "open to startups worldwide, except in Cuba"}],
        "confidence": 0.9,
    }
    for path, value in overrides.items():
        target = d
        keys = path.split("__")
        for k in keys[:-1]:
            target = target[k]
        target[keys[-1]] = value
    return d


GOOD_ANSWERS = {"answers": [
    {"question": "Company name", "answer": "Exemplo Tecnologia Ltda", "source_fields": ["legal_name"],
     "needs_user_input": False, "note": ""},
    {"question": "Website", "answer": "https://exemplo.com.br", "source_fields": ["website"],
     "needs_user_input": False, "note": ""},
    {"question": "Founded", "answer": "March 15, 2024", "source_fields": ["founded_date"],
     "needs_user_input": False, "note": ""},
    {"question": "Total funding (USD)", "answer": "0", "source_fields": ["total_funding_usd"],
     "needs_user_input": False, "note": ""},
]}


class FakeLLM:
    def __init__(self, responses: dict | None = None):
        self.responses = responses or {}
        self.calls: list[tuple[str, str]] = []

    def _get(self, purpose, prompt, schema):
        self.calls.append((purpose, prompt))
        r = self.responses[purpose]
        result = r(prompt) if callable(r) else r
        validate(result, schema)
        return copy.deepcopy(result)

    def json(self, *, purpose, system, prompt, schema, effort):
        return self._get(purpose, prompt, schema)

    def research(self, *, purpose, system, prompt, report_tool, server_tools, effort):
        return self._get(purpose, prompt, report_tool["input_schema"])


class FakeFetcher:
    def __init__(self, pages: dict[str, FetchResult | str]):
        self.pages = pages
        self.calls: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.calls.append(url)
        page = self.pages.get(url)
        if page is None:
            return FetchResult(url=url, status=404, error="HTTP 404")
        if isinstance(page, FetchResult):
            return page
        return FetchResult(url=url, final_url=url, status=200, title="t", text=page)


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    c = Config(base_dir=tmp_path, data_dir=tmp_path / "data", profile_path=tmp_path / "company_profile.toml")
    c.discovery.seeds_file = str(tmp_path / "seeds.toml")
    c.fetch.delay_seconds = 0
    return c


@pytest.fixture
def db(cfg) -> Database:
    return Database(cfg.db_path)


def verified(value, source="doc"):
    return {"value": value, "verified": True, "source": source, "verified_at": "2026-11-01"}


@pytest.fixture
def profile() -> CompanyProfile:
    return CompanyProfile.from_dict({
        "legal_name": verified("Exemplo Tecnologia Ltda"),
        "country": verified("BR"),
        "founded_date": verified("2024-03-15"),
        "is_incorporated": verified(True),
        "website": verified("https://exemplo.com.br"),
        "total_funding_usd": verified(0),
        "stage": verified("pre_seed"),
        "investors": verified([]),
        "accelerators": verified([]),
        "contact_email": {"value": "ceo@exemplo.com.br", "verified": False},
    })


def add_verified_program(db, key="acme:acme-cloud-for-startups", details=None, url="https://acme.com/startups"):
    from credits_agent.db import dumps
    from credits_agent.discovery import core_hash

    details = details or make_details()
    pid = db.insert_program(key=key, provider="Acme", name="Acme Cloud for Startups", category="cloud", url=url,
                            official_domains=["acme.com"], source="seed")
    db.update_program(pid, status="verified", details_json=dumps(details), details_hash=core_hash(details),
                      evidence_check="ok")
    db.conn.commit()
    return db.program(pid)
