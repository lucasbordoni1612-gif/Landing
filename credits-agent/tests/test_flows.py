from datetime import date
from email.message import EmailMessage

import pytest

from credits_agent.applications import (PreparationError, SubmissionBlocked, approve, mark_submitted,
                                        prepare_application, reject, set_answer, submit_application)
from credits_agent.db import DuplicateApplication, loads
from credits_agent.discovery import load_seeds, validate_candidate, verify_program
from credits_agent.fetcher import FetchResult
from credits_agent.inbox import check_inbox, sender_authenticated
from credits_agent.pipeline import run_daily
from credits_agent.profile import CompanyProfile
from credits_agent.report import RunReport
from credits_agent.submitter import Submitter

from .conftest import GOOD_ANSWERS, PAGE_TEXT, FakeFetcher, FakeLLM, add_verified_program, make_details, verified

TODAY = date(2026, 11, 16)
URL = "https://acme.com/startups"


# --- discovery / verification -----------------------------------------------------

def test_seeds_are_idempotent(db, tmp_path):
    seeds = tmp_path / "s.toml"
    seeds.write_text('[[program]]\nprovider="Acme"\nname="Acme Cloud for Startups"\ncategory="cloud"\n'
                     f'url="{URL}"\nofficial_domains=["acme.com"]\n')
    assert load_seeds(db, seeds) == 1
    assert load_seeds(db, seeds) == 0


def test_candidate_validation(db):
    add_verified_program(db)
    ok = {"provider": "Beta AI", "program_name": "Beta AI Startup Credits", "category": "ai_api",
          "official_url": "https://beta.ai/startups", "official_domains": ["beta.ai"], "why_official": "",
          "lead_source_url": ""}
    assert validate_candidate(db, ok) == (True, "")
    assert not validate_candidate(db, {**ok, "official_url": "https://medium.com/@x/beta-credits",
                                       "official_domains": ["medium.com"]})[0]
    assert not validate_candidate(db, {**ok, "official_url": "https://blog.other.io/beta"})[0]
    assert not validate_candidate(db, {**ok, "official_url": "http://beta.ai/startups"})[0]
    dup = {**ok, "provider": "Acme Inc", "program_name": "Acme Cloud Startup Program",
           "official_url": "https://acme.com/startup-program", "official_domains": ["acme.com"]}
    assert not validate_candidate(db, dup)[0]


def _new_program(db):
    pid = db.insert_program(key="acme:acme-cloud-for-startups", provider="Acme", name="Acme Cloud for Startups",
                            category="other", url=URL, official_domains=["acme.com"], source="seed")
    db.conn.commit()
    return pid


def test_verify_extracts_once_and_detects_changes(db, cfg):
    pid = _new_program(db)
    llm = FakeLLM({"extract_program": make_details()})
    fetcher = FakeFetcher({URL: PAGE_TEXT})
    report = RunReport(TODAY)
    verify_program(db, llm, fetcher, cfg, db.program(pid), report, TODAY)
    p = db.program(pid)
    assert p["status"] == "verified" and p["evidence_check"] == "ok" and p["category"] == "cloud"
    assert len(llm.calls) == 1 and report.sections["verified_programs"]

    verify_program(db, llm, fetcher, cfg, db.program(pid), report, TODAY)  # same content: no model call
    assert len(llm.calls) == 1

    llm.responses["extract_program"] = make_details(benefit__max_value=50000)
    fetcher.pages[URL] = PAGE_TEXT + " Now up to $50,000."
    verify_program(db, llm, fetcher, cfg, db.program(pid), report, TODAY)
    assert len(llm.calls) == 2
    assert any("benefit.max_value: 25000 → 50000" in line for line in report.sections["changed_programs"])


def test_verify_rejects_offdomain_redirect_and_js_pages(db, cfg):
    pid = _new_program(db)
    fetcher = FakeFetcher({URL: FetchResult(url=URL, final_url="https://phish.io/x", status=200, text=PAGE_TEXT)})
    verify_program(db, FakeLLM(), fetcher, cfg, db.program(pid), RunReport(TODAY), TODAY)
    assert db.program(pid)["status"] == "url_broken"

    db.update_program(pid, status="unverified")
    llm = FakeLLM({"extract_program_web_fetch": make_details()})
    verify_program(db, llm, FakeFetcher({URL: "tiny js shell"}), cfg, db.program(pid), RunReport(TODAY), TODAY)
    assert llm.calls[0][0] == "extract_program_web_fetch"
    assert db.program(pid)["evidence_check"] == "not_verifiable"


# --- applications ------------------------------------------------------------------

def test_prepare_approve_submit_manual(db, cfg, profile):
    p = add_verified_program(db)
    llm = FakeLLM({"draft_application": GOOD_ANSWERS})
    app_id = prepare_application(db, llm, cfg, profile, p, today=TODAY)
    app = db.application(app_id)
    assert app["status"] == "awaiting_approval"
    assert "contact_email" not in llm.calls[0][1]  # unverified data never leaves the machine

    with pytest.raises(DuplicateApplication):
        prepare_application(db, llm, cfg, profile, p, today=TODAY)
    with pytest.raises(SubmissionBlocked):
        submit_application(db, cfg, profile, app_id, Submitter(cfg), TODAY)  # not approved yet

    approve(db, app_id, approver="tester")
    outcome = submit_application(db, cfg, profile, app_id, Submitter(cfg), TODAY)
    assert outcome.status == "awaiting_manual_submission"
    text = open(outcome.ref, encoding="utf-8").read()
    assert "Exemplo Tecnologia Ltda" in text and "https://acme.com/startups/apply" in text
    with pytest.raises(SubmissionBlocked):
        submit_application(db, cfg, profile, app_id, Submitter(cfg), TODAY)  # never twice
    mark_submitted(db, app_id)
    assert db.application(app_id)["status"] == "submitted"


def test_ungrounded_answer_becomes_draft_and_needs_user(db, cfg, profile):
    p = add_verified_program(db)
    answers = {"answers": [dict(a) for a in GOOD_ANSWERS["answers"]]}
    answers["answers"][3] = {**answers["answers"][3], "answer": "We raised $300,000"}  # invented
    app_id = prepare_application(db, FakeLLM({"draft_application": answers}), cfg, profile, p, today=TODAY)
    app = db.application(app_id)
    assert app["status"] == "draft"
    assert loads(app["missing_json"])[0]["index"] == 3
    with pytest.raises(PreparationError):
        approve(db, app_id)
    assert set_answer(db, app_id, 3, "0") == "awaiting_approval"
    approve(db, app_id)
    set_answer(db, app_id, 0, "Exemplo Tecnologia LTDA")  # edit after approval voids it
    assert db.application(app_id)["status"] == "awaiting_approval"
    reject(db, app_id, "não quero")
    assert db.application(app_id)["status"] == "rejected_by_user"


def test_ineligible_and_unverified_programs_are_not_prepared(db, cfg, profile):
    p = add_verified_program(db, details=make_details(geography__excluded_countries=["BR"]))
    with pytest.raises(PreparationError, match="inelegível"):
        prepare_application(db, FakeLLM(), cfg, profile, p, today=TODAY)
    unverified = CompanyProfile.from_dict({"legal_name": verified("X")})
    p2 = add_verified_program(db, key="acme:other", url="https://acme.com/other")
    with pytest.raises(PreparationError, match="não verificados"):
        prepare_application(db, FakeLLM(), cfg, unverified, p2, today=TODAY)


def test_profile_change_after_approval_supersedes(db, cfg, profile):
    p = add_verified_program(db)
    app_id = prepare_application(db, FakeLLM({"draft_application": GOOD_ANSWERS}), cfg, profile, p, today=TODAY)
    approve(db, app_id)
    changed = CompanyProfile.from_dict({**{k: verified(v.value) for k, v in profile.fields.items() if v.verified},
                                        "employees": verified(5)})
    with pytest.raises(SubmissionBlocked, match="mudaram"):
        submit_application(db, cfg, changed, app_id, Submitter(cfg), TODAY)
    assert db.application(app_id)["status"] == "superseded"


class NoSmtp:
    configured = False


class FakeSmtp:
    configured = True

    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)
        return "<sent-1@exemplo.com.br>"


def test_email_submission_only_to_official_domain(db, cfg, profile):
    details = make_details(application__method="email", application__email_address="startups@acme.com")
    p = add_verified_program(db, details=details)
    app_id = prepare_application(db, FakeLLM({"draft_application": GOOD_ANSWERS}), cfg, profile, p, today=TODAY)
    approve(db, app_id)
    smtp = FakeSmtp()
    outcome = submit_application(db, cfg, profile, app_id, Submitter(cfg, smtp), TODAY)
    assert outcome.status == "submitted" and smtp.sent[0]["To"] == "startups@acme.com"
    assert db.application(app_id)["submission_ref"] == "<sent-1@exemplo.com.br>"

    evil = make_details(application__method="email", application__email_address="apply@evil.io")
    p2 = add_verified_program(db, key="acme:evil", details=evil, url="https://acme.com/evil")
    app2 = prepare_application(db, FakeLLM({"draft_application": GOOD_ANSWERS}), cfg, profile, p2, today=TODAY)
    approve(db, app2)
    assert submit_application(db, cfg, profile, app2, Submitter(cfg, smtp), TODAY).method == "manual"
    assert len(smtp.sent) == 1


# --- inbox -----------------------------------------------------------------------

AUTH_OK = "mx.google.com; dkim=pass header.i=@acme.com header.s=s1; dmarc=pass (p=REJECT) header.from=acme.com"


def _mail(mid, subject, body, auth=AUTH_OK, sender="Acme Startups <startups@mail.acme.com>"):
    m = EmailMessage()
    m["From"], m["Subject"], m["Message-ID"], m["Date"] = sender, subject, mid, "Mon, 16 Nov 2026 10:00:00 +0000"
    if auth:
        m["Authentication-Results"] = auth
    m.set_content(body)
    return m.as_bytes()


class FakeMail:
    def __init__(self, messages):
        self.messages = messages

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def search(self, since, domains):
        return list(self.messages)

    def fetch_headers(self, uid):
        return self.messages[uid]

    def fetch(self, uid):
        return self.messages[uid]


GRANTED = {"program_key": "acme:acme-cloud-for-startups", "event": "credits_granted",
           "credits": [{"amount": 25000, "currency": "USD", "description": "Acme credits", "expires_at": ""}],
           "action_required": "", "action_deadline": "", "summary_pt": "Créditos concedidos.",
           "evidence_quote": "We have added $25,000 in credits"}


def test_inbox_registers_credits_once_and_accepts_application(db, cfg, profile):
    p = add_verified_program(db)
    app_id = prepare_application(db, FakeLLM({"draft_application": GOOD_ANSWERS}), cfg, profile, p, today=TODAY)
    approve(db, app_id)
    submit_application(db, cfg, profile, app_id, Submitter(cfg), TODAY)
    mail = FakeMail({"1": _mail("<m1@acme.com>", "Your Acme credits are ready",
                                "Congratulations! We have added $25,000 in credits to your account.")})
    llm = FakeLLM({"classify_email": GRANTED})
    report = RunReport(TODAY)
    check_inbox(db, llm, mail, cfg, report, TODAY)
    credits = db.credits_with_balance()
    assert len(credits) == 1 and credits[0]["amount"] == 25000
    assert credits[0]["expires_at"] == "2027-11-16"  # 12-month validity rule from the program page
    assert db.application(app_id)["status"] == "accepted"
    check_inbox(db, llm, mail, cfg, report, TODAY)  # same Message-ID: ignored
    assert len(db.credits_with_balance()) == 1 and len(llm.calls) == 1


def test_inbox_unauthenticated_or_ungrounded_mail_changes_nothing(db, cfg):
    add_verified_program(db)
    mail = FakeMail({
        "1": _mail("<x1@acme.com>", "Your credits", "We have added $25,000 in credits", auth=None),
        "2": _mail("<x2@acme.com>", "Your credits", "Congratulations, credits were added to your account."),
    })
    report = RunReport(TODAY)
    check_inbox(db, FakeLLM({"classify_email": GRANTED}), mail, cfg, report, TODAY)
    assert db.credits_with_balance() == []
    joined = " ".join(report.sections["manual_review"])
    assert "DKIM/DMARC" in joined and "não aparece no e-mail" in joined


def test_sender_authentication_trusts_only_own_server():
    import email
    from email import policy

    forged = email.message_from_bytes(
        _mail("<f@x>", "s", "b", auth="attacker.example; dkim=pass header.d=acme.com"), policy=policy.default)
    assert not sender_authenticated(forged, "acme.com", "mx.google.com")
    real = email.message_from_bytes(_mail("<r@x>", "s", "b"), policy=policy.default)
    assert sender_authenticated(real, "mail.acme.com", "mx.google.com")
    assert not sender_authenticated(real, "evil.io", "mx.google.com")


def test_irrelevant_mail_is_skipped_without_model_call(db, cfg):
    add_verified_program(db)
    mail = FakeMail({"1": _mail("<n@acme.com>", "Your invoice", "Monthly invoice attached.")})
    llm = FakeLLM()
    check_inbox(db, llm, mail, cfg, RunReport(TODAY), TODAY)
    assert llm.calls == [] and db.email_processed("<n@acme.com>")


# --- full daily run -----------------------------------------------------------------

def test_run_daily_end_to_end(db, cfg, profile, tmp_path):
    (tmp_path / "seeds.toml").write_text(
        '[[program]]\nprovider="Acme"\nname="Acme Cloud for Startups"\ncategory="cloud"\n'
        f'url="{URL}"\nofficial_domains=["acme.com"]\n')
    llm = FakeLLM({
        "discovery": {"candidates": [{"provider": "Beta AI", "program_name": "Beta Startup Credits",
                                      "category": "ai_api", "official_url": "https://beta.ai/startups",
                                      "official_domains": ["beta.ai"], "why_official": "página do provedor",
                                      "lead_source_url": "https://blog.example/list"}]},
        "extract_program": make_details(),
        "draft_application": GOOD_ANSWERS,
    })
    fetcher = FakeFetcher({URL: PAGE_TEXT})  # beta.ai page missing -> reported, not fatal
    cfg.email.enabled = False
    report, path = run_daily(cfg, db, llm, profile, fetcher=fetcher, smtp=NoSmtp(), today=TODAY)
    text = path.read_text(encoding="utf-8")
    assert "Aguardando sua aprovação (1)" in text
    assert "Beta AI — Beta Startup Credits" in text
    pending = db.applications(("awaiting_approval",))
    assert len(pending) == 1

    approve(db, pending[0]["id"])
    report2, _ = run_daily(cfg, db, llm, profile, fetcher=fetcher, smtp=NoSmtp(), today=TODAY)
    assert db.application(pending[0]["id"])["status"] == "awaiting_manual_submission"
    assert report2.sections["submissions"]
    assert len(db.applications()) == 1  # no duplicate draft on the second run
    assert not report.sections.get("errors") and not report2.sections.get("errors")
