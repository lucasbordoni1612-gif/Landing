"""Outgoing e-mail through the user's own SMTP account (digest and, when a
program officially accepts it, approved applications sent by e-mail)."""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from .config import SmtpConfig, secret


class SmtpSender:
    def __init__(self, cfg: SmtpConfig):
        self.cfg = cfg
        self.user = secret(cfg.user_env)
        self.password = secret(cfg.password_env)
        self.notify_to = secret(cfg.notify_to_env) or self.user

    @property
    def configured(self) -> bool:
        return bool(self.cfg.enabled and self.user and self.password)

    def send(self, msg: EmailMessage) -> str:
        if not self.configured:
            raise RuntimeError("SMTP não configurado (veja [smtp] no config.toml e as variáveis de ambiente)")
        if "From" not in msg:
            msg["From"] = self.user
        msg["Date"] = formatdate(localtime=True)
        if "Message-ID" not in msg:
            msg["Message-ID"] = make_msgid(domain=self.user.split("@")[-1])
        with smtplib.SMTP(self.cfg.host, self.cfg.port, timeout=60) as smtp:
            smtp.starttls()
            smtp.login(self.user, self.password)
            smtp.send_message(msg)
        return str(msg["Message-ID"])

    def send_digest(self, subject: str, body: str) -> str:
        msg = EmailMessage()
        msg["To"] = self.notify_to
        msg["Subject"] = subject
        msg.set_content(body)
        return self.send(msg)
