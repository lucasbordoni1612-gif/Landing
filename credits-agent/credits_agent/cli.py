"""Command line: `credits-agent <comando>`. Run `credits-agent -h` for the list."""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
from datetime import date
from pathlib import Path

from .applications import (PreparationError, SubmissionBlocked, approve, mark_submitted, prepare_application,
                           reject, set_answer, submit_application)
from .config import Config, load_config
from .db import Database, DuplicateApplication, dumps, loads
from .discovery import load_seeds, verify_program
from .eligibility import evaluate_program
from .fetcher import Fetcher
from .inbox import ImapMailSource, check_inbox
from .llm import ClaudeLLM
from .notify import SmtpSender
from .pipeline import refresh_eligibility, run_daily, run_lock
from .profile import FIELD_CATALOG, CompanyProfile
from .report import RunReport
from .submitter import Submitter

PACKAGE_DIR = Path(__file__).resolve().parent.parent
ICONS = {"pass": "✔", "fail": "✘", "unknown": "?", "info": "i"}


def _has_claude_credentials() -> bool:
    env = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE", "ANTHROPIC_FEDERATION_RULE_ID")
    return any(os.environ.get(k) for k in env) or (Path.home() / ".config" / "anthropic").exists()


def make_llm(cfg: Config, required: bool = False) -> ClaudeLLM | None:
    if not _has_claude_credentials():
        if required:
            sys.exit("Erro: configure a API do Claude (ANTHROPIC_API_KEY ou `ant auth login`).")
        return None
    return ClaudeLLM(cfg.llm)


def load_profile(cfg: Config) -> CompanyProfile:
    if not cfg.profile_path.exists():
        sys.exit(f"Erro: perfil da empresa não encontrado em {cfg.profile_path}. Rode `credits-agent init`.")
    return CompanyProfile.load(cfg.profile_path)


def _program_or_exit(db: Database, key: str):
    p = db.program(key)
    if p is None:
        sys.exit(f"Erro: programa '{key}' não encontrado (veja `credits-agent programs`).")
    return p


def _money(value, currency="") -> str:
    return "—" if value is None else f"{float(value):,.0f} {currency}".strip()


# --- commands ----------------------------------------------------------------

def cmd_init(cfg: Config, args) -> None:
    for example, target in (("config.example.toml", cfg.base_dir / "config.toml"),
                            ("company_profile.example.toml", cfg.profile_path)):
        src = PACKAGE_DIR / example
        if not target.exists() and src.exists():
            shutil.copy(src, target)
            print(f"criado {target} (edite antes de usar)")
    db = Database(cfg.db_path)
    added = load_seeds(db, cfg.resolve(cfg.discovery.seeds_file))
    print(f"banco em {cfg.db_path}; {added} programa(s) semente adicionados")


def cmd_run_daily(cfg: Config, args) -> None:
    db = Database(cfg.db_path)
    report, path = run_daily(cfg, db, make_llm(cfg), load_profile(cfg))
    print(path.read_text(encoding="utf-8").split("\n\n---\n\n")[-1])
    print(f"\nRelatório salvo em {path}")


def cmd_verify(cfg: Config, args) -> None:
    db, llm, profile = Database(cfg.db_path), make_llm(cfg, required=True), load_profile(cfg)
    report = RunReport(date.today())
    with run_lock(cfg.data_dir):
        p = _program_or_exit(db, args.key)
        db.update_program(p["id"], content_hash=None)  # force a fresh extraction
        db.conn.commit()
        verify_program(db, llm, Fetcher(cfg.fetch), cfg, db.program(p["id"]), report, date.today())
        refresh_eligibility(db, profile, date.today())
    for section, lines in report.sections.items():
        for line in lines:
            print(f"[{section}] {line}")
    cmd_show(cfg, args)


def cmd_programs(cfg: Config, args) -> None:
    db = Database(cfg.db_path)
    rows = db.programs(args.status)
    if args.eligible:
        rows = [r for r in rows if r["eligibility_overall"] == "eligible"]
    print(f"{'chave':45} {'status':15} {'elegib.':13} {'valor máx.':>14}  categoria")
    for r in rows:
        d = loads(r["details_json"], {}) or {}
        b = d.get("benefit", {})
        print(f"{r['key'][:45]:45} {r['status']:15} {(r['eligibility_overall'] or '-'):13} "
              f"{_money(b.get('max_value'), b.get('currency', '')):>14}  {r['category']}")
    print(f"\n{len(rows)} programa(s)")


def cmd_show(cfg: Config, args) -> None:
    db = Database(cfg.db_path)
    p = _program_or_exit(db, args.key)
    d = loads(p["details_json"], {}) or {}
    print(f"{p['provider']} — {p['name']}  [{p['key']}]")
    print(f"URL oficial: {p['official_url']}\nStatus: {p['status']} | verificado em: {p['last_verified_at'] or 'nunca'}"
          f" | evidências: {p['evidence_check'] or '-'}")
    if not d:
        return
    b, g, e, dl, a, t = (d[k] for k in ("benefit", "geography", "eligibility", "deadlines", "application", "terms"))
    print(f"\n{d.get('summary_pt', '')}\n")
    print(f"Benefício: {b['value_description']} (máx. {_money(b['max_value'], b['currency'])}; "
          f"validade {b['credit_validity_months'] or '?'} meses)")
    print(f"Prazo: {dl['application_deadline'] or ('contínuo' if dl['rolling'] else 'não informado')} {dl['notes']}")
    print(f"Geografia: {g['scope']} | permitidos: {', '.join(g['allowed_countries']) or '-'} | "
          f"excluídos: {', '.join(g['excluded_countries']) or '-'} {g['notes']}")
    print(f"Estágios: {', '.join(e['stages_allowed']) or '-'} | idade máx.: {e['max_company_age_years'] or '-'} anos | "
          f"captação máx.: {_money(e['max_total_funding_usd'], 'USD')}")
    for req in e["other_requirements"]:
        print(f"  • {req}")
    print(f"Inscrição: {a['method']} {a['url'] or a['email_address']}")
    print(f"Termos: {t['terms_url'] or '-'} | um por empresa: {t['one_per_company']} | "
          f"não acumula com: {', '.join(t['exclusive_with']) or '-'} | automação proibida: {t['automation_prohibited']}")
    elig = loads(p["eligibility_json"])
    if elig:
        print(f"\nElegibilidade: {elig['overall']}")
        for c in elig["checks"]:
            print(f"  {ICONS[c['result']]} {c['name']}: {c['detail']}")


def cmd_profile(cfg: Config, args) -> None:
    profile = load_profile(cfg)
    facts = profile.verified_facts()
    print(f"{len(facts)} campo(s) verificado(s) e utilizáveis:")
    for name in facts:
        f = profile.fields[name]
        print(f"  ✔ {name}: {FIELD_CATALOG.get(name, '')} — fonte: {f.source or '?'} ({f.verified_at or '?'})")
    issues = profile.issues()
    if issues:
        print("\nPendências (estes dados NÃO serão usados até serem verificados):")
        for name, problem in issues:
            print(f"  ✘ {name} ({FIELD_CATALOG.get(name, '')}): {problem}")


def cmd_prepare(cfg: Config, args) -> None:
    db, profile = Database(cfg.db_path), load_profile(cfg)
    llm = make_llm(cfg, required=True)
    p = _program_or_exit(db, args.key)
    try:
        app_id = prepare_application(db, llm, cfg, profile, p, force=args.force)
    except (PreparationError, DuplicateApplication) as exc:
        sys.exit(f"Não preparado: {exc}")
    print(f"Rascunho #{app_id} criado ({db.application(app_id)['status']}). Revise: credits-agent review {app_id}")


def cmd_applications(cfg: Config, args) -> None:
    db = Database(cfg.db_path)
    statuses = ("awaiting_approval",) if args.pending else None
    rows = db.applications(statuses)
    for a in rows:
        packet = loads(a["packet_json"], {})
        print(f"#{a['id']:<4} {a['status']:27} {packet.get('provider', '')} — {packet.get('program_name', '')}"
              f"  (atualizado {a['updated_at'][:10]})")
    if not rows:
        print("nenhuma inscrição" + (" aguardando aprovação" if args.pending else ""))


def _print_packet(app, packet) -> None:
    print(f"Inscrição #{app['id']} — {packet['provider']}: {packet['program_name']}  [status: {app['status']}]")
    print(f"Benefício: {packet['benefit'] or '?'} | prazo: {packet['deadline'] or 'não informado'}")
    how = ("e-mail para " + packet["target_email"]) if packet["method"] == "email" and packet["target_email"] \
        else f"formulário oficial: {packet['target_url']} (você envia; o agente prepara o texto)"
    print(f"Envio: {how}\nTermos: {packet['terms_url'] or packet['official_url']}\n")
    elig = loads(app["eligibility_json"], {})
    print(f"Elegibilidade no preparo: {elig.get('overall')}")
    for c in elig.get("checks", []):
        print(f"  {ICONS[c['result']]} {c['name']}: {c['detail']}")
    print("\nRespostas:")
    for i, a in enumerate(packet["answers"], 1):
        flag = "  ⚠ FALTA: " + a.get("note", "") if a.get("needs_user_input") else ""
        print(f"  {i}. {a['question']}\n     → {a['answer'] or '(vazio)'}   [fonte: {', '.join(a['source_fields']) or '-'}]{flag}")
    if packet["required_documents"]:
        print("\nDocumentos pedidos: " + "; ".join(packet["required_documents"]))
    if packet["confirmations"]:
        print("\nAo aprovar você confirma que leu/atende:")
        for c in packet["confirmations"]:
            print(f"  - {c}")


def cmd_review(cfg: Config, args) -> None:
    db = Database(cfg.db_path)
    app = db.application(args.id)
    if app is None:
        sys.exit(f"inscrição {args.id} não existe")
    _print_packet(app, loads(app["packet_json"]))
    missing = loads(app["missing_json"], [])
    if missing:
        print(f"\nPreencha com: credits-agent set-answer {args.id} <número> \"texto\"  (ou verifique o campo no perfil "
              f"e rode prepare de novo)")
    elif app["status"] == "awaiting_approval":
        print(f"\nPara aprovar: credits-agent approve {args.id}    | recusar: credits-agent reject {args.id}")


def cmd_set_answer(cfg: Config, args) -> None:
    db = Database(cfg.db_path)
    try:
        status = set_answer(db, args.id, args.number - 1, args.text)
    except (KeyError, IndexError, PreparationError) as exc:
        sys.exit(f"Erro: {exc}")
    print(f"Resposta {args.number} atualizada; inscrição agora em '{status}' (aprovação anterior, se havia, foi anulada).")


def cmd_approve(cfg: Config, args) -> None:
    db = Database(cfg.db_path)
    app = db.application(args.id)
    if app is None:
        sys.exit(f"inscrição {args.id} não existe")
    packet = loads(app["packet_json"])
    if not args.yes:
        _print_packet(app, packet)
        answer = input(f"\nDigite APROVAR para autorizar o envio desta inscrição a {packet['provider']}: ").strip()
        if answer != "APROVAR":
            sys.exit("Aprovação cancelada.")
    try:
        approve(db, args.id)
    except (KeyError, PreparationError) as exc:
        sys.exit(f"Erro: {exc}")
    print(f"Inscrição #{args.id} aprovada.")
    if args.submit:
        cmd_submit(cfg, args)
    else:
        print("Será enviada na próxima execução diária (ou agora: credits-agent submit "
              f"{args.id}).")


def cmd_reject(cfg: Config, args) -> None:
    db = Database(cfg.db_path)
    try:
        reject(db, args.id, args.reason)
    except (KeyError, PreparationError) as exc:
        sys.exit(f"Erro: {exc}")
    print(f"Inscrição #{args.id} recusada; o agente não preparará este programa de novo automaticamente.")


def cmd_submit(cfg: Config, args) -> None:
    db, profile = Database(cfg.db_path), load_profile(cfg)
    with run_lock(cfg.data_dir):
        try:
            outcome = submit_application(db, cfg, profile, args.id, Submitter(cfg, SmtpSender(cfg.smtp)))
        except (KeyError, SubmissionBlocked) as exc:
            sys.exit(f"Não enviado: {exc}")
    print(outcome.message)


def cmd_mark_submitted(cfg: Config, args) -> None:
    db = Database(cfg.db_path)
    try:
        mark_submitted(db, args.id, args.ref or "")
    except (KeyError, SubmissionBlocked) as exc:
        sys.exit(f"Erro: {exc}")
    print(f"Inscrição #{args.id} marcada como enviada. O agente vai acompanhar os e-mails de resposta.")


def cmd_inbox(cfg: Config, args) -> None:
    db, llm = Database(cfg.db_path), make_llm(cfg, required=True)
    report = RunReport(date.today())
    with run_lock(cfg.data_dir), ImapMailSource(cfg.email) as source:
        n = check_inbox(db, llm, source, cfg, report)
    print(f"{n} e-mail(s) analisado(s)")
    for section, lines in report.sections.items():
        for line in lines:
            print(f"[{section}] {line}")


def cmd_credits(cfg: Config, args) -> None:
    db = Database(cfg.db_path)
    if args.action == "add":
        program = _program_or_exit(db, args.program) if args.program else None
        with db.tx():
            cid = db.insert_credit(provider=args.provider or (program["provider"] if program else "?"),
                                   amount=args.amount, currency=args.currency, source="manual",
                                   program_id=program["id"] if program else None, description=args.description,
                                   granted_at=args.granted or date.today().isoformat(), expires_at=args.expires)
        print(f"crédito #{cid} registrado")
        return
    if args.action == "use":
        with db.tx():
            db.add_usage(args.credit_id, args.amount, args.date or date.today().isoformat(), args.note)
        print("uso registrado")
        return
    rows = db.credits_with_balance()
    if args.action == "expiring":
        limit = date.fromordinal(date.today().toordinal() + args.days).isoformat()
        rows = [r for r in rows if r["state"] in ("available", "partially_used") and r["expires_at"]
                and r["expires_at"] <= limit]
    print(f"{'id':>4} {'provedor':22} {'total':>12} {'usado':>12} {'saldo':>12} {'moeda':5} {'expira':10} estado")
    for r in rows:
        print(f"{r['id']:>4} {r['provider'][:22]:22} {r['amount']:>12,.2f} {r['used']:>12,.2f} {r['remaining']:>12,.2f} "
              f"{r['currency']:5} {r['expires_at'] or '-':10} {r['state']}")


def cmd_report(cfg: Config, args) -> None:
    db = Database(cfg.db_path)
    print(RunReport(date.today()).render(db))


def cmd_export(cfg: Config, args) -> None:
    db = Database(cfg.db_path)
    data = {
        "programs": [dict(r) for r in db.programs()],
        "applications": [dict(r) for r in db.applications()],
        "credits": db.credits_with_balance(),
    }
    Path(args.output).write_text(dumps(data), encoding="utf-8")
    print(f"exportado para {args.output}")


# --- parser ------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="credits-agent", description="Agente de créditos para startups")
    parser.add_argument("--config", default=os.environ.get("CREDITS_AGENT_CONFIG", "config.toml"))
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(fn=fn)
        return sp

    add("init", cmd_init, "cria config, perfil de exemplo e banco")
    add("run-daily", cmd_run_daily, "execução diária completa")
    add("verify", cmd_verify, "reverifica um programa agora").add_argument("key")
    sp = add("programs", cmd_programs, "lista programas")
    sp.add_argument("--status")
    sp.add_argument("--eligible", action="store_true")
    add("show", cmd_show, "detalhes de um programa").add_argument("key")
    add("profile", cmd_profile, "mostra dados verificados e pendências do perfil")
    sp = add("prepare", cmd_prepare, "prepara rascunho de inscrição")
    sp.add_argument("key")
    sp.add_argument("--force", action="store_true", help="aceita elegibilidade 'needs_review' (após você confirmar)")
    sp = add("applications", cmd_applications, "lista inscrições")
    sp.add_argument("--pending", action="store_true")
    add("review", cmd_review, "mostra o pacote de uma inscrição").add_argument("id", type=int)
    sp = add("set-answer", cmd_set_answer, "preenche/corrige uma resposta")
    sp.add_argument("id", type=int)
    sp.add_argument("number", type=int)
    sp.add_argument("text")
    sp = add("approve", cmd_approve, "aprova uma inscrição para envio")
    sp.add_argument("id", type=int)
    sp.add_argument("--yes", action="store_true", help="não pedir confirmação interativa")
    sp.add_argument("--submit", action="store_true", help="enviar imediatamente após aprovar")
    sp = add("reject", cmd_reject, "recusa um rascunho")
    sp.add_argument("id", type=int)
    sp.add_argument("--reason", default="")
    add("submit", cmd_submit, "envia uma inscrição aprovada").add_argument("id", type=int)
    sp = add("mark-submitted", cmd_mark_submitted, "confirma que você enviou no site oficial")
    sp.add_argument("id", type=int)
    sp.add_argument("--ref")
    add("inbox", cmd_inbox, "lê e-mails de resposta dos programas")
    sp = add("credits", cmd_credits, "banco de créditos")
    csub = sp.add_subparsers(dest="action", required=True)
    csub.add_parser("list")
    ex = csub.add_parser("expiring")
    ex.add_argument("--days", type=int, default=30)
    ca = csub.add_parser("add")
    ca.add_argument("--amount", type=float, required=True)
    ca.add_argument("--currency", default="USD")
    ca.add_argument("--provider")
    ca.add_argument("--program", help="chave do programa")
    ca.add_argument("--expires", help="AAAA-MM-DD")
    ca.add_argument("--granted", help="AAAA-MM-DD")
    ca.add_argument("--description", default="")
    cu = csub.add_parser("use")
    cu.add_argument("credit_id", type=int)
    cu.add_argument("amount", type=float)
    cu.add_argument("--date")
    cu.add_argument("--note", default="")
    add("report", cmd_report, "mostra o relatório atual sem rodar nada")
    add("export", cmd_export, "exporta o banco em JSON").add_argument("output")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    (cfg.data_dir / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(cfg.data_dir / "logs" / "agent.log", encoding="utf-8")],
    )
    args.fn(cfg, args)


if __name__ == "__main__":
    main()
