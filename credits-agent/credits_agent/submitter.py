"""Sending an approved application.

* E-mail: only when the official page says applications go to an e-mail address
  on the provider's own domain, SMTP is configured and the terms do not forbid
  automation. Sent from your own account, with your approved text.
* Everything else (web forms, partner portals, logins, CAPTCHAs): the agent
  writes a ready-to-paste packet and opens nothing on your behalf. Filling
  third-party forms with bots usually breaks their terms of use.
"""
from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from .config import Config
from .db import dumps
from .notify import SmtpSender
from .util import host_in_domains, slugify


@dataclass
class SubmissionOutcome:
    status: str   # submitted | awaiting_manual_submission
    method: str   # email | manual
    ref: str      # Message-ID or packet path
    message: str


def render_packet_markdown(app_id: int, packet: dict) -> str:
    lines = [
        f"# Inscrição #{app_id} — {packet['provider']}: {packet['program_name']}",
        "",
        f"- Página oficial: {packet['official_url']}",
        f"- Onde enviar: {packet['target_url']}" + (f" ou {packet['target_email']}" if packet.get("target_email") else ""),
        f"- Benefício: {packet.get('benefit') or 'não informado'}",
        f"- Prazo: {packet.get('deadline') or 'não informado / fluxo contínuo'}",
        f"- Termos: {packet.get('terms_url') or 'ver página oficial'}",
        "",
        "## Respostas aprovadas (copie e cole no formulário oficial)",
        "",
    ]
    for i, a in enumerate(packet["answers"], 1):
        lines += [f"### {i}. {a['question']}", "", a["answer"] or "_(sem resposta)_", ""]
    if packet.get("required_documents"):
        lines += ["## Documentos pedidos", ""] + [f"- {d}" for d in packet["required_documents"]] + [""]
    if packet.get("confirmations"):
        lines += ["## Confirme antes de enviar", ""] + [f"- [ ] {c}" for c in packet["confirmations"]] + [""]
    lines += [
        "## Depois de enviar",
        "",
        f"Rode `credits-agent mark-submitted {app_id}` (ou o agente detecta sozinho o e-mail de confirmação).",
        "",
    ]
    return "\n".join(lines)


class Submitter:
    def __init__(self, cfg: Config, smtp: SmtpSender | None = None):
        self.cfg = cfg
        self.smtp = smtp

    def _can_email(self, packet: dict, details: dict) -> bool:
        target = packet.get("target_email") or ""
        return bool(
            packet.get("method") == "email"
            and target
            and host_in_domains(target.split("@")[-1], packet.get("official_domains", []))
            and self.cfg.applications.allow_email_submission
            and self.smtp is not None and self.smtp.configured
            and not details.get("terms", {}).get("automation_prohibited")
        )

    def submit(self, app_id: int, packet: dict, details: dict) -> SubmissionOutcome:
        if self._can_email(packet, details):
            msg = EmailMessage()
            msg["To"] = packet["target_email"]
            msg["Subject"] = f"Application: {packet['program_name']}"
            body = [f"Hello {packet['provider']} team,", "",
                    f"Please find below our application to {packet['program_name']}.", ""]
            for a in packet["answers"]:
                body += [f"{a['question']}", f"{a['answer']}", ""]
            body += ["Thank you."]
            msg.set_content("\n".join(body))
            ref = self.smtp.send(msg)
            return SubmissionOutcome("submitted", "email", ref, f"enviada por e-mail para {packet['target_email']}")

        out_dir = self.cfg.packets_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        base = out_dir / f"app-{app_id}-{slugify(packet['program_key'])}"
        Path(f"{base}.md").write_text(render_packet_markdown(app_id, packet), encoding="utf-8")
        Path(f"{base}.json").write_text(dumps(packet), encoding="utf-8")
        return SubmissionOutcome("awaiting_manual_submission", "manual", f"{base}.md",
                                 f"pacote pronto em {base}.md — envie em {packet['target_url']}")
