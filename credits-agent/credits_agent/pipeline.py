"""The daily run, step by step. Every step is isolated: a failure is written
to the report and the next step still runs."""
from __future__ import annotations

import fcntl
import logging
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Callable, Iterator

from .applications import PreparationError, SubmissionBlocked, prepare_application, submit_application
from .config import Config
from .db import Database, DuplicateApplication, dumps
from .discovery import discover_new_programs, load_seeds, programs_due, verify_program
from .eligibility import evaluate_program
from .fetcher import Fetcher
from .inbox import ImapMailSource, MailSource, check_inbox
from .llm import LLMClient
from .notify import SmtpSender
from .profile import CompanyProfile
from .report import RunReport
from .submitter import Submitter
from .util import utcnow_iso

log = logging.getLogger(__name__)


@contextmanager
def run_lock(data_dir: Path) -> Iterator[None]:
    data_dir.mkdir(parents=True, exist_ok=True)
    with open(data_dir / "agent.lock", "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("outra execução do agente está em andamento") from None
        yield


def refresh_eligibility(db: Database, profile: CompanyProfile, today: date) -> None:
    with db.tx():
        for p in db.programs("verified"):
            elig = evaluate_program(db, p, profile, today)
            if elig:
                db.update_program(p["id"], eligibility_json=dumps(elig), eligibility_overall=elig["overall"],
                                  eligibility_at=utcnow_iso())


def auto_prepare(db: Database, llm: LLMClient, cfg: Config, profile: CompanyProfile, report: RunReport,
                 today: date) -> None:
    rows = db.q(
        """SELECT * FROM programs WHERE status = 'verified' AND eligibility_overall = 'eligible'
             AND COALESCE(evidence_check, '') NOT IN ('weak', 'none')
             AND id NOT IN (SELECT program_id FROM applications WHERE status != 'superseded')
           ORDER BY provider LIMIT ?""",
        (cfg.applications.max_drafts_per_run,),
    )
    for p in rows:
        try:
            app_id = prepare_application(db, llm, cfg, profile, p, today=today)
        except (PreparationError, DuplicateApplication) as exc:
            report.add("verification_problems", f"{p['provider']} — {p['name']}: rascunho não criado: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - keep the run going
            report.add("errors", f"{p['provider']} — {p['name']}: falha ao preparar: {exc}")
            continue
        app = db.application(app_id)
        report.add("drafts", f"#{app_id} {p['provider']} — {p['name']} ({app['status']})")


def submit_approved(db: Database, cfg: Config, profile: CompanyProfile, submitter: Submitter,
                    report: RunReport, today: date) -> None:
    for app in db.applications(("approved",)):
        try:
            outcome = submit_application(db, cfg, profile, app["id"], submitter, today)
            report.add("submissions", f"#{app['id']}: {outcome.message}")
        except SubmissionBlocked as exc:
            report.add("manual_review", f"Inscrição #{app['id']} não enviada: {exc}")
        except Exception as exc:  # noqa: BLE001
            report.add("errors", f"Inscrição #{app['id']}: falha no envio: {exc}")
    for app in db.applications(("submitting",)):
        report.add("manual_review", f"Inscrição #{app['id']} ficou em 'submitting' (envio interrompido). "
                                    "Confira se chegou ao programa antes de qualquer nova ação.")


def run_daily(cfg: Config, db: Database, llm: LLMClient | None, profile: CompanyProfile,
              fetcher: Fetcher | None = None, mail_source_factory: Callable[[], MailSource] | None = None,
              smtp: SmtpSender | None = None, today: date | None = None) -> tuple[RunReport, Path]:
    today = today or date.today()
    report = RunReport(today)
    fetcher = fetcher or Fetcher(cfg.fetch)
    smtp = smtp or SmtpSender(cfg.smtp)

    def step(name: str, fn: Callable[[], object]) -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            log.exception("step %s failed", name)
            db.conn.rollback()
            report.add("errors", f"Etapa '{name}': {exc}")

    with run_lock(cfg.data_dir):
        step("sementes", lambda: load_seeds(db, cfg.resolve(cfg.discovery.seeds_file)))
        if llm is None:
            report.add("errors", "API do Claude não configurada: descoberta, extração, rascunhos e leitura de "
                                 "e-mails foram pulados (defina ANTHROPIC_API_KEY)")
        else:
            if cfg.discovery.enabled:
                step("descoberta", lambda: discover_new_programs(db, llm, cfg, profile.get("country"), report, today))

            def verify_all() -> None:
                for p in programs_due(db, cfg):
                    try:
                        verify_program(db, llm, fetcher, cfg, p, report, today)
                    except Exception as exc:  # noqa: BLE001
                        db.conn.rollback()
                        report.add("errors", f"{p['provider']} — {p['name']}: {exc}")

            step("verificação", verify_all)
        step("elegibilidade", lambda: refresh_eligibility(db, profile, today))
        if llm is not None and cfg.applications.auto_prepare:
            step("rascunhos", lambda: auto_prepare(db, llm, cfg, profile, report, today))
        if cfg.applications.auto_submit_approved:
            step("envio", lambda: submit_approved(db, cfg, profile, Submitter(cfg, smtp), report, today))
        if llm is not None and cfg.email.enabled:
            def inbox() -> None:
                factory = mail_source_factory or (lambda: ImapMailSource(cfg.email))
                with factory() as source:
                    check_inbox(db, llm, source, cfg, report, today)
            step("e-mails", inbox)
        issues = profile.issues(today)
        if issues:
            report.add("manual_review", f"Perfil da empresa: {len(issues)} campo(s) ausentes, não verificados ou "
                                        "antigos — rode `credits-agent profile` para ver quais")
        with db.tx():
            db.set_meta("last_run_at", utcnow_iso())
        path = report.save(db, cfg.reports_dir)
        if smtp.configured:
            step("notificação", lambda: smtp.send_digest(f"[credits-agent] Relatório {today.isoformat()}",
                                                         path.read_text(encoding="utf-8")))
    return report, path
