# memory/audit/ — İç Denetim durumu (3. savunma hattı)

- `findings_register.jsonl` — append-only bulgu takibi (son satır = güncel durum).
  Şema: finding_id, control_id, severity, owner, auditor, title, status
  (OPEN→CLOSED/REOPENED), opened_at, due_at, doc_path, remediation_doc,
  verified_at, recurrence_count.
  `AuditAgentBase.emit_finding` / `verify_remediation` tarafından yazılır.

Bulgu doc'ları `reports/audit/` altında (audit_finding / audit_report /
audit_followup / audit_assurance). Denetim evreni: `configs/audit_universe.yaml`.
