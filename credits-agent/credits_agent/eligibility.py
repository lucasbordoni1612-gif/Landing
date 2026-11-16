"""Deterministic eligibility rules: program facts (extracted from the official
page) versus *verified* company facts. The model never decides eligibility.

Each check yields one of:
  pass     - requirement met
  fail     - requirement not met (program becomes ineligible)
  unknown  - cannot decide with verified data (program needs review)
  info     - shown to the user, does not block
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date

from .db import ACTIVE_APP_STATUSES, Database, loads
from .profile import CompanyProfile
from .util import parse_date, similar_names, slugify

STAGE_ORDER = ["idea", "pre_seed", "seed", "series_a", "series_b", "series_c_plus"]


@dataclass
class Check:
    name: str
    result: str
    detail: str


@dataclass
class History:
    """What the company already has, so the same benefit is never claimed twice."""
    engaged_program_names: list[str] = field(default_factory=list)  # active apps or credits (other programs)
    credited_providers: set[str] = field(default_factory=set)        # provider slugs with credits on record
    rejections: list[date] = field(default_factory=list)             # this program's past rejections
    self_credited: bool = False                                      # credits already recorded for this program
    user_declined: bool = False                                      # user rejected a draft before


def build_history(db: Database, program_id: int, provider: str) -> History:
    h = History()
    marks = ",".join("?" * len(ACTIVE_APP_STATUSES))
    for row in db.q(
        f"""SELECT DISTINCT p.name FROM programs p
            WHERE p.id != ? AND (
              EXISTS (SELECT 1 FROM applications a WHERE a.program_id = p.id AND a.status IN ({marks}))
              OR EXISTS (SELECT 1 FROM credits c WHERE c.program_id = p.id))""",
        (program_id, *ACTIVE_APP_STATUSES),
    ):
        h.engaged_program_names.append(row["name"])
    for row in db.q("SELECT DISTINCT provider, program_id FROM credits"):
        if row["program_id"] == program_id:
            h.self_credited = True
        else:
            h.credited_providers.add(slugify(row["provider"]))
    for app in db.applications_for_program(program_id):
        if app["status"] == "rejected":
            d = parse_date(app["decision_at"] or app["updated_at"])
            if d:
                h.rejections.append(d)
        if app["status"] == "rejected_by_user":
            h.user_declined = True
    return h


def _months_between(a: date, b: date) -> float:
    return (b - a).days / 30.44


def evaluate(details: dict, profile: CompanyProfile, history: History, today: date | None = None,
             program_name: str = "", provider: str = "") -> dict:
    today = today or date.today()
    checks: list[Check] = []
    add = lambda n, r, d: checks.append(Check(n, r, d))  # noqa: E731

    status = details.get("program_status", "unknown")
    method = details.get("application", {}).get("method", "unknown")
    if status in ("closed", "paused"):
        add("programa_aberto", "fail", f"programa está '{status}' segundo a página oficial")
    elif status == "invite_only" or method == "invite_only":
        add("programa_aberto", "fail", "somente por convite")
    elif status == "unknown":
        add("programa_aberto", "unknown", "página não deixa claro se o programa está aberto")
    else:
        add("programa_aberto", "pass", "aberto")

    deadlines = details.get("deadlines", {})
    deadline = parse_date(deadlines.get("application_deadline"))
    if deadline and deadline < today:
        add("prazo", "fail", f"prazo encerrado em {deadline.isoformat()}")
    elif deadline:
        add("prazo", "pass", f"inscrições até {deadline.isoformat()} ({(deadline - today).days} dias)")
    else:
        add("prazo", "info", "fluxo contínuo" if deadlines.get("rolling") else "prazo não informado")

    geo = details.get("geography", {})
    country = (profile.get("country") or "").upper()
    allowed = [c.upper() for c in geo.get("allowed_countries", [])]
    excluded = [c.upper() for c in geo.get("excluded_countries", [])]
    if not country:
        add("geografia", "unknown", "país da empresa não verificado no perfil")
    elif country in excluded:
        add("geografia", "fail", f"{country} está na lista de países excluídos")
    elif allowed and country not in allowed:
        add("geografia", "fail", f"{country} fora dos países permitidos ({', '.join(allowed)})")
    elif allowed or geo.get("scope") == "worldwide":
        add("geografia", "pass", f"{country} elegível")
    else:
        add("geografia", "unknown", f"restrição geográfica não clara: {geo.get('notes') or 'sem detalhes'}")

    elig = details.get("eligibility", {})
    stages = [s for s in elig.get("stages_allowed", []) if s != "any"]
    if stages and "any" not in elig.get("stages_allowed", []):
        stage = profile.get("stage")
        if not stage:
            add("estagio", "unknown", f"programa aceita {stages}; estágio da empresa não verificado")
        elif stage in stages:
            add("estagio", "pass", f"estágio {stage} aceito")
        else:
            add("estagio", "fail", f"estágio {stage} não está entre {stages}")

    def numeric(name: str, label: str, value, limit, mode: str) -> None:
        if limit is None:
            return
        if value is None:
            add(name, "unknown", f"{label}: limite {limit:,.0f}, valor da empresa não verificado")
            return
        ok = float(value) <= float(limit) if mode == "max" else float(value) >= float(limit)
        word = "máximo" if mode == "max" else "mínimo"
        add(name, "pass" if ok else "fail", f"{label}: empresa {float(value):,.1f} / {word} {float(limit):,.1f}")

    numeric("idade_empresa", "idade (anos)", profile.company_age_years(today), elig.get("max_company_age_years"), "max")
    numeric("captacao_max", "captação USD", profile.get("total_funding_usd"), elig.get("max_total_funding_usd"), "max")
    numeric("captacao_min", "captação USD", profile.get("total_funding_usd"), elig.get("min_total_funding_usd"), "min")
    numeric("receita", "receita anual USD", profile.get("annual_revenue_usd"), elig.get("max_annual_revenue_usd"), "max")

    if elig.get("requires_incorporation"):
        inc = profile.get("is_incorporated")
        add("constituicao", "unknown" if inc is None else ("pass" if inc else "fail"),
            "exige empresa constituída" + ("" if inc is not None else " (não verificado)"))

    if elig.get("requires_vc_or_accelerator_backing"):
        backers = (profile.get("investors") or []) + (profile.get("accelerators") or [])
        both_verified = all(profile.fields.get(f) and profile.fields[f].verified for f in ("investors", "accelerators"))
        if backers:
            add("investidor_aceleradora", "pass", f"apoio verificado: {', '.join(backers)}")
        elif both_verified:
            add("investidor_aceleradora", "fail", "exige investidor/aceleradora parceira; perfil declara nenhum")
        else:
            add("investidor_aceleradora", "unknown", "exige investidor/aceleradora; dado não verificado")
        add("parceiro_listado", "info", "confirme se seu investidor/aceleradora é parceiro oficial do programa")

    if elig.get("requires_partner_referral_code"):
        add("codigo_parceiro", "unknown", "exige código de indicação de parceiro (obtenha com sua aceleradora/VC)")
    if elig.get("requires_new_customer"):
        add("cliente_novo", "unknown", "exige que a empresa nunca tenha sido cliente pagante do provedor")
    if elig.get("requires_company_email_domain"):
        domain, email = profile.get("email_domain"), profile.get("contact_email") or ""
        ok = bool(domain and email.lower().endswith("@" + str(domain).lower()))
        add("email_corporativo", "pass" if ok else "unknown", "exige e-mail no domínio da empresa")
    if elig.get("requires_public_website"):
        add("site_publico", "pass" if profile.get("website") else "unknown", "exige site público")
    for req in elig.get("other_requirements", []):
        add("requisito_extra", "info", req)

    # --- terms / duplicates ---------------------------------------------------
    terms = details.get("terms", {})
    previous = profile.get("previous_programs") or []
    if any(similar_names(p, program_name) for p in previous):
        add("ja_recebido", "fail", "perfil informa que a empresa já recebeu este programa")
    if history.self_credited:
        add("ja_recebido", "fail", "já existem créditos deste programa registrados no banco")
    if terms.get("one_per_company") and slugify(provider) in history.credited_providers:
        add("um_por_empresa", "unknown",
            f"programa é um por empresa e já há créditos de {provider} de outro programa: confirme nos termos")
    for other in terms.get("exclusive_with", []):
        clash = [n for n in history.engaged_program_names + previous if similar_names(n, other)]
        if clash:
            add("exclusividade", "fail", f"não acumulável com '{other}' (empresa já tem: {', '.join(clash)})")
    if history.rejections:
        last = max(history.rejections)
        cooldown = terms.get("reapply_cooldown_months")
        if cooldown is None:
            add("reinscricao", "unknown", f"inscrição recusada em {last.isoformat()}; termos não dizem quando reaplicar")
        elif _months_between(last, today) < float(cooldown):
            add("reinscricao", "fail", f"recusada em {last.isoformat()}; aguardar {cooldown:.0f} meses")
        else:
            add("reinscricao", "pass", "carência de reinscrição cumprida")
    if history.user_declined:
        add("decisao_usuario", "info", "você recusou um rascunho deste programa antes")
    if terms.get("automation_prohibited"):
        add("automacao", "info", "termos proíbem automação: envio será sempre manual por você")

    if any(c.result == "fail" for c in checks):
        overall = "ineligible"
    elif any(c.result == "unknown" for c in checks):
        overall = "needs_review"
    else:
        overall = "eligible"
    return {"overall": overall, "checks": [asdict(c) for c in checks], "evaluated_on": today.isoformat()}


def evaluate_program(db: Database, program, profile: CompanyProfile, today: date | None = None) -> dict | None:
    details = loads(program["details_json"])
    if not details or program["status"] != "verified":
        return None
    history = build_history(db, program["id"], program["provider"])
    return evaluate(details, profile, history, today, program_name=program["name"], provider=program["provider"])
