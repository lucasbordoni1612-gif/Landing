"""Agent configuration (config.toml). Secrets never live here: only the *names*
of the environment variables that hold them."""
from __future__ import annotations

import os
import tomllib
import warnings
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any


@dataclass
class LLMConfig:
    model: str = "claude-opus-5-5"
    effort_extraction: str = "medium"
    effort_discovery: str = "high"
    effort_drafting: str = "high"
    effort_email: str = "medium"
    max_tokens: int = 16000
    # Server-side refusal fallback ("default" lets the API pick by refusal category).
    # Set to "" to disable.
    fallbacks: str = "default"
    max_web_searches: int = 8


@dataclass
class DiscoveryConfig:
    enabled: bool = True
    seeds_file: str = "sources/seed_programs.toml"
    queries_per_day: int = 3
    max_new_candidates_per_day: int = 15
    verify_interval_days: int = 1
    max_verifications_per_run: int = 80
    queries: list[str] = field(default_factory=lambda: [
        "official startup program free cloud credits",
        "AI API credits for startups official program",
        "LLM API startup program free credits apply",
        "GPU cloud credits startups program apply",
        "developer tools free for startups program official",
        "database free credits startup program",
        "SaaS perks for early-stage startups official program",
        "programa de créditos para startups cloud oficial Brasil",
        "startup program credits Latin America startups eligible Brazil",
        "vector database startup program credits",
        "observability monitoring free for startups program",
        "speech AI API startup grants credits",
    ])


@dataclass
class FetchConfig:
    user_agent: str = "CreditsDiscoveryAgent/0.1 (+automated research; respects robots.txt)"
    delay_seconds: float = 3.0
    timeout_seconds: float = 30.0
    max_bytes: int = 3_000_000
    min_text_chars: int = 800
    max_text_chars_for_llm: int = 120_000


@dataclass
class ApplicationsConfig:
    auto_prepare: bool = True
    max_drafts_per_run: int = 5
    language: str = "English"
    auto_submit_approved: bool = True
    allow_email_submission: bool = True


@dataclass
class EmailConfig:
    enabled: bool = False
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    mailbox: str = "INBOX"
    lookback_days: int = 21
    user_env: str = "CREDITS_AGENT_IMAP_USER"
    password_env: str = "CREDITS_AGENT_IMAP_PASSWORD"
    # Only Authentication-Results headers stamped by this server are trusted
    # (Gmail: "mx.google.com"). Empty = trust only the topmost header.
    trusted_authserv_id: str = "mx.google.com"
    keywords: list[str] = field(default_factory=lambda: [
        "credit", "crédito", "credito", "startup", "activate", "founders", "inception",
        "program", "programa", "application", "inscrição", "inscricao", "approved",
        "aprovad", "welcome", "bem-vindo", "promo code", "coupon", "cupom", "benefit",
        "benefício", "expire", "expira", "grant",
    ])


@dataclass
class SmtpConfig:
    enabled: bool = False
    host: str = "smtp.gmail.com"
    port: int = 587
    user_env: str = "CREDITS_AGENT_SMTP_USER"
    password_env: str = "CREDITS_AGENT_SMTP_PASSWORD"
    notify_to_env: str = "CREDITS_AGENT_NOTIFY_TO"


@dataclass
class Config:
    base_dir: Path
    data_dir: Path
    profile_path: Path
    llm: LLMConfig = field(default_factory=LLMConfig)
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    fetch: FetchConfig = field(default_factory=FetchConfig)
    applications: ApplicationsConfig = field(default_factory=ApplicationsConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    smtp: SmtpConfig = field(default_factory=SmtpConfig)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "credits.db"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def packets_dir(self) -> Path:
        return self.data_dir / "packets"

    def resolve(self, relative: str) -> Path:
        p = Path(relative)
        return p if p.is_absolute() else self.base_dir / p


def _build(cls, raw: dict[str, Any], section: str):
    known = {f.name for f in fields(cls)}
    unknown = set(raw) - known
    if unknown:
        warnings.warn(f"config.toml [{section}]: chaves desconhecidas ignoradas: {sorted(unknown)}")
    return cls(**{k: v for k, v in raw.items() if k in known})


def load_config(path: str | Path | None) -> Config:
    path = Path(path) if path else None
    raw: dict[str, Any] = {}
    base = Path.cwd()
    if path and path.exists():
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        base = path.resolve().parent
    agent = raw.get("agent", {})
    cfg = Config(
        base_dir=base,
        data_dir=(base / agent.get("data_dir", "data")).resolve(),
        profile_path=(base / agent.get("company_profile", "company_profile.toml")).resolve(),
        llm=_build(LLMConfig, raw.get("llm", {}), "llm"),
        discovery=_build(DiscoveryConfig, raw.get("discovery", {}), "discovery"),
        fetch=_build(FetchConfig, raw.get("fetch", {}), "fetch"),
        applications=_build(ApplicationsConfig, raw.get("applications", {}), "applications"),
        email=_build(EmailConfig, raw.get("email", {}), "email"),
        smtp=_build(SmtpConfig, raw.get("smtp", {}), "smtp"),
    )
    return cfg


def secret(env_name: str) -> str | None:
    value = os.environ.get(env_name, "").strip()
    return value or None
