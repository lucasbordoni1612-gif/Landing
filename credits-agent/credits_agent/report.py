"""Daily digest: what changed today plus everything that is waiting for you."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

SECTION_TITLES = {
    "manual_review": "⚠️ Precisa da sua atenção",
    "submissions": "Inscrições enviadas / prontas para envio manual",
    "drafts": "Novos rascunhos de inscrição",
    "email_events": "E-mails dos programas",
    "new_programs": "Novos programas descobertos",
    "verified_programs": "Programas verificados pela primeira vez",
    "changed_programs": "Mudanças em programas (valor, prazo, regras)",
    "verification_problems": "Problemas de verificação",
    "rejected_candidates": "Pistas descartadas (não oficiais ou duplicadas)",
    "errors": "Erros",
}


@dataclass
class RunReport:
    today: date
    sections: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    def add(self, section: str, line: str) -> None:
        self.sections[section].append(line)

    def render(self, db) -> str:
        from .db import loads  # local import avoids a cycle

        out = [f"# Relatório diário de créditos — {self.today.isoformat()}", ""]

        pending = db.applications(("awaiting_approval",))
        out.append(f"## ✅ Aguardando sua aprovação ({len(pending)})")
        if not pending:
            out.append("- nada pendente")
        for app in pending:
            packet = loads(app["packet_json"], {})
            out.append(f"- #{app['id']} **{packet.get('provider')} — {packet.get('program_name')}**: "
                       f"{packet.get('benefit', '')}  → revisar: `credits-agent review {app['id']}`")
        out.append("")

        drafts = db.applications(("draft",))
        if drafts:
            out.append(f"## 📝 Rascunhos com dados faltando ({len(drafts)})")
            for app in drafts:
                packet = loads(app["packet_json"], {})
                missing = loads(app["missing_json"], [])
                out.append(f"- #{app['id']} {packet.get('provider')} — {packet.get('program_name')}: faltam "
                           + "; ".join(m.get("question", str(m)) for m in missing[:6]))
            out.append("")

        manual = db.applications(("awaiting_manual_submission",))
        if manual:
            out.append(f"## 📤 Aprovadas, aguardando você enviar no site oficial ({len(manual)})")
            for app in manual:
                packet = loads(app["packet_json"], {})
                out.append(f"- #{app['id']} {packet.get('program_name')}: {packet.get('target_url')} "
                           f"(pacote: {app['submission_ref']}; depois `credits-agent mark-submitted {app['id']}`)")
            out.append("")

        for key, title in SECTION_TITLES.items():
            lines = self.sections.get(key)
            if lines:
                out.append(f"## {title} ({len(lines)})")
                out.extend(f"- {line}" for line in lines)
                out.append("")

        review = db.q("SELECT * FROM programs WHERE status = 'verified' AND eligibility_overall = 'needs_review' "
                      "AND id NOT IN (SELECT program_id FROM applications) ORDER BY provider")
        if review:
            out.append(f"## 🔎 Programas que dependem de dado não verificado ({len(review)})")
            for p in review:
                elig = loads(p["eligibility_json"], {})
                unknown = [c["detail"] for c in elig.get("checks", []) if c["result"] == "unknown"]
                out.append(f"- {p['provider']} — {p['name']}: " + "; ".join(unknown[:3])
                           + f"  → `credits-agent prepare {p['key']} --force` após confirmar")
            out.append("")

        credits = db.credits_with_balance()
        live = [c for c in credits if c["state"] in ("available", "partially_used")]
        soon = [c for c in live if c["expires_at"] and c["expires_at"] <= (self.today + timedelta(days=30)).isoformat()]
        out.append("## 💳 Créditos")
        totals: dict[str, float] = defaultdict(float)
        for c in live:
            totals[c["currency"]] += c["remaining"]
        out.append("- saldo disponível: " + (", ".join(f"{v:,.2f} {k}" for k, v in sorted(totals.items())) or "nenhum"))
        for c in soon:
            out.append(f"- ⏰ expira em {c['expires_at']}: #{c['id']} {c['provider']} {c['remaining']:,.2f} {c['currency']}")
        out.append("")
        return "\n".join(out)

    def save(self, db, reports_dir: Path) -> Path:
        reports_dir.mkdir(parents=True, exist_ok=True)
        path = reports_dir / f"{self.today.isoformat()}.md"
        text = self.render(db)
        if path.exists():  # several runs on the same day: keep all of them
            text = path.read_text(encoding="utf-8") + "\n\n---\n\n" + text
        path.write_text(text, encoding="utf-8")
        return path
