"""Company profile with per-field verification.

Only fields marked ``verified = true`` are ever used to judge eligibility or to
fill an application. Everything else is treated as unknown.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .util import parse_date, sha256_json

# Field name -> human description (pt-BR). Fields not listed are still allowed.
FIELD_CATALOG: dict[str, str] = {
    "legal_name": "Razão social",
    "trade_name": "Nome fantasia / marca",
    "tax_id": "CNPJ (ou registro equivalente)",
    "country": "País de constituição (código ISO de 2 letras, ex.: BR)",
    "state": "Estado",
    "city": "Cidade",
    "founded_date": "Data de fundação (AAAA-MM-DD)",
    "is_incorporated": "Empresa formalmente constituída (true/false)",
    "website": "Site oficial (https://...)",
    "email_domain": "Domínio de e-mail corporativo (ex.: minhaempresa.com.br)",
    "contact_name": "Nome do responsável pela inscrição",
    "contact_email": "E-mail corporativo do responsável",
    "contact_role": "Cargo do responsável",
    "contact_linkedin": "LinkedIn do responsável",
    "company_linkedin": "LinkedIn da empresa",
    "employees": "Número de funcionários",
    "stage": "Estágio (idea, pre_seed, seed, series_a, series_b, series_c_plus)",
    "total_funding_usd": "Captação total em USD (0 se bootstrapped)",
    "annual_revenue_usd": "Receita anual em USD",
    "investors": "Lista de investidores institucionais",
    "accelerators": "Lista de aceleradoras / incubadoras",
    "industry": "Setor",
    "product_description_short": "Descrição curta do produto (1-2 frases)",
    "product_description_long": "Descrição detalhada do produto",
    "credits_use_case": "Como a empresa usará os créditos",
    "tech_stack": "Tecnologias utilizadas",
    "product_live": "Produto já em produção (true/false)",
    "github_org": "Organização no GitHub",
    "pitch_deck_url": "Link do pitch deck",
    "previous_programs": "Programas de créditos já recebidos antes (lista de nomes)",
}

STALE_AFTER_DAYS = 365


def _normalize(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == []


@dataclass
class ProfileField:
    name: str
    value: Any
    verified: bool
    source: str = ""
    verified_at: str = ""


class CompanyProfile:
    def __init__(self, fields: dict[str, ProfileField]):
        self.fields = fields

    @classmethod
    def load(cls, path: str | Path) -> "CompanyProfile":
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CompanyProfile":
        fields: dict[str, ProfileField] = {}
        for name, spec in raw.items():
            if name == "meta" or not isinstance(spec, dict):
                continue
            fields[name] = ProfileField(
                name=name,
                value=_normalize(spec.get("value")),
                verified=bool(spec.get("verified", False)),
                source=str(spec.get("source", "")),
                verified_at=str(_normalize(spec.get("verified_at", "")) or ""),
            )
        return cls(fields)

    def get(self, name: str) -> Any:
        """Value of a *verified*, non-empty field, else None."""
        f = self.fields.get(name)
        if f is None or not f.verified or _empty(f.value):
            return None
        return f.value

    def verified_facts(self) -> dict[str, Any]:
        return {n: f.value for n, f in sorted(self.fields.items()) if f.verified and not _empty(f.value)}

    def hash(self) -> str:
        return sha256_json(self.verified_facts())

    def issues(self, today: date | None = None) -> list[tuple[str, str]]:
        today = today or date.today()
        out: list[tuple[str, str]] = []
        for name in FIELD_CATALOG:
            f = self.fields.get(name)
            if f is None or _empty(f.value):
                out.append((name, "ausente"))
            elif not f.verified:
                out.append((name, "não verificado"))
            else:
                if not f.source:
                    out.append((name, "verificado sem fonte informada"))
                checked = parse_date(f.verified_at)
                if checked and (today - checked).days > STALE_AFTER_DAYS:
                    out.append((name, f"verificação com mais de {STALE_AFTER_DAYS} dias"))
        return out

    def company_age_years(self, today: date | None = None) -> float | None:
        founded = parse_date(self.get("founded_date"))
        if not founded:
            return None
        return ((today or date.today()) - founded).days / 365.25
