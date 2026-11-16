"""JSON schemas for everything the model returns, plus a small validator used on
tool inputs (which, unlike `output_config.format`, are not schema-enforced here)."""
from __future__ import annotations

from typing import Any

STR = {"type": "string"}
NUM = {"type": "number"}
BOOL = {"type": "boolean"}


def nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def arr(items: dict) -> dict:
    return {"type": "array", "items": items}


def enum(*values: str) -> dict:
    return {"type": "string", "enum": list(values)}


def obj(props: dict[str, dict]) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


CATEGORIES = ("ai_api", "cloud", "database", "devtools", "observability", "saas", "communication", "other")
STAGES = ("idea", "pre_seed", "seed", "series_a", "series_b", "series_c_plus", "any")

PROGRAM_DETAILS_SCHEMA = obj({
    "is_program_page": BOOL,
    "published_by_provider": BOOL,
    "provider": STR,
    "program_name": STR,
    "category": enum(*CATEGORIES),
    "summary_pt": STR,
    "program_status": enum("open", "closed", "paused", "invite_only", "unknown"),
    "official_domains": arr(STR),
    "benefit": obj({
        "benefit_type": enum("cloud_credits", "api_credits", "software_discount", "free_plan",
                             "cash_grant", "mixed", "other"),
        "max_value": nullable(NUM),
        "currency": STR,
        "value_description": STR,
        "credit_validity_months": nullable(NUM),
        "tiers": arr(obj({"name": STR, "value": nullable(NUM), "requirements": STR})),
    }),
    "eligibility": obj({
        "stages_allowed": arr(enum(*STAGES)),
        "max_company_age_years": nullable(NUM),
        "max_total_funding_usd": nullable(NUM),
        "min_total_funding_usd": nullable(NUM),
        "max_annual_revenue_usd": nullable(NUM),
        "requires_incorporation": nullable(BOOL),
        "requires_vc_or_accelerator_backing": nullable(BOOL),
        "requires_partner_referral_code": nullable(BOOL),
        "requires_new_customer": nullable(BOOL),
        "requires_company_email_domain": nullable(BOOL),
        "requires_public_website": nullable(BOOL),
        "other_requirements": arr(STR),
    }),
    "geography": obj({
        "scope": enum("worldwide", "restricted", "unknown"),
        "allowed_countries": arr(STR),
        "excluded_countries": arr(STR),
        "notes": STR,
    }),
    "deadlines": obj({
        "application_deadline": STR,
        "rolling": nullable(BOOL),
        "notes": STR,
    }),
    "application": obj({
        "method": enum("web_form", "email", "partner_portal", "invite_only", "unknown"),
        "url": STR,
        "email_address": STR,
        "requires_account_login": nullable(BOOL),
        "required_fields": arr(STR),
        "required_documents": arr(STR),
    }),
    "terms": obj({
        "terms_url": STR,
        "one_per_company": nullable(BOOL),
        "exclusive_with": arr(STR),
        "reapply_cooldown_months": nullable(NUM),
        "prohibited_practices": arr(STR),
        "automation_prohibited": nullable(BOOL),
        "notes": STR,
    }),
    "evidence": arr(obj({"claim": STR, "quote": STR})),
    "confidence": NUM,
})

TERMS_SCHEMA = PROGRAM_DETAILS_SCHEMA["properties"]["terms"]
TERMS_EXTRACTION_SCHEMA = obj({
    "terms": TERMS_SCHEMA,
    "geography_restrictions": obj({"allowed_countries": arr(STR), "excluded_countries": arr(STR), "notes": STR}),
    "evidence": arr(obj({"claim": STR, "quote": STR})),
})

CANDIDATES_TOOL = {
    "name": "record_program_candidates",
    "description": (
        "Record the official startup credit/benefit programs you found. Call it exactly once, "
        "at the end of your research, with every new candidate (an empty list if none)."
    ),
    "input_schema": obj({
        "candidates": arr(obj({
            "provider": STR,
            "program_name": STR,
            "category": enum(*CATEGORIES),
            "official_url": STR,
            "official_domains": arr(STR),
            "why_official": STR,
            "lead_source_url": STR,
        })),
    }),
}

DETAILS_TOOL = {
    "name": "record_program_details",
    "description": "Record the facts extracted from the official program page. Call it exactly once.",
    "input_schema": PROGRAM_DETAILS_SCHEMA,
}

ANSWERS_SCHEMA = obj({
    "answers": arr(obj({
        "question": STR,
        "answer": STR,
        "source_fields": arr(STR),
        "needs_user_input": BOOL,
        "note": STR,
    })),
})

EMAIL_EVENTS = ("application_received", "approved", "credits_granted", "rejected",
                "more_info_requested", "credits_expiring", "usage_notice", "marketing", "unrelated")

EMAIL_CLASSIFICATION_SCHEMA = obj({
    "program_key": STR,
    "event": enum(*EMAIL_EVENTS),
    "credits": arr(obj({"amount": NUM, "currency": STR, "description": STR, "expires_at": STR})),
    "action_required": STR,
    "action_deadline": STR,
    "summary_pt": STR,
    "evidence_quote": STR,
})


class SchemaError(ValueError):
    pass


_TYPES = {
    "string": str, "number": (int, float), "integer": int, "boolean": bool,
    "array": list, "object": dict, "null": type(None),
}


def validate(value: Any, schema: dict, path: str = "$") -> None:
    """Validate the subset of JSON Schema used above. Raises SchemaError."""
    if "anyOf" in schema:
        errors = []
        for option in schema["anyOf"]:
            try:
                validate(value, option, path)
                return
            except SchemaError as exc:
                errors.append(str(exc))
        raise SchemaError(f"{path}: nenhum tipo aceito ({'; '.join(errors)})")
    expected = schema.get("type")
    if expected:
        py = _TYPES[expected]
        if isinstance(value, bool) and expected in ("number", "integer"):
            raise SchemaError(f"{path}: esperado {expected}, veio boolean")
        if not isinstance(value, py):
            raise SchemaError(f"{path}: esperado {expected}, veio {type(value).__name__}")
    if "enum" in schema and value not in schema["enum"]:
        raise SchemaError(f"{path}: valor {value!r} fora de {schema['enum']}")
    if expected == "object":
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in value:
                raise SchemaError(f"{path}: campo obrigatório ausente: {req}")
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(props)
            if extra:
                raise SchemaError(f"{path}: campos não permitidos: {sorted(extra)}")
        for k, v in value.items():
            if k in props:
                validate(v, props[k], f"{path}.{k}")
    if expected == "array" and "items" in schema:
        for i, item in enumerate(value):
            validate(item, schema["items"], f"{path}[{i}]")
