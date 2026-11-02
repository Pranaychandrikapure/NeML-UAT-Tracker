# CReMS PRD

## Original problem statement
User provided a long "MASTER DEVELOPMENT PROMPT" for CReMS — Change & Release Management System: centralized management of Change Requests (Zoho + internal), BA review, Senior PM/PM impact analysis & deadline negotiation, CR assignment hierarchy, multiple dev tasks per CR with self-assignment, Development & SIT statuses, backend-controlled automatic CR status transitions, SRN (Software Release Note) generation in the supplied DOCX format, multi-level SRN approvals (TL & PM → BA → UAT) with hold/reject/request-changes/resume and revision invalidation, UAT deployment tracking (separate from approval), automatic SRN emails with To/CC and threads, UAT testing, bug assignment/fix/SIT/release/retest, consolidated role-specific dashboards with 12 KPIs, notifications/reminders, audit trail, reports, hierarchical user management with configurable role-grant policies and project-level RBAC, projects/modules/screens, Zoho Projects sync with integration health. Requested stack Next.js/Postgres/Redis/Celery; references: org hierarchy, CR assignment and SRN approval diagrams, Zoho JSON sample, SRN DOCX.
User choices: build on platform stack (React+FastAPI+MongoDB); Emergent-managed Google Sign-In + Email/Password; Zoho built, connect later; Emergent managed Resend email; clearly labelled demo data. "make simple view and beneficial to all across company, production level design".

## Architecture
See /app/README.md. Modular FastAPI monolith, MongoDB, Clerk auth with provisioned-user check, in-process outbox worker for emails and reminders.

## Personas
System Admin, Project Lead, Senior PM, PM, Team Lead, Developer, BA Lead, BA, UAT Lead, UAT Manager, UAT Member.

## Implemented (2026-11-02)
- Auth: Clerk sign-in; only provisioned active users (403 NOT_PROVISIONED / ACCOUNT_INACTIVE); ADMIN_EMAIL auto System Admin; demo act-as for admin (audited)
- Users: hierarchical creation with backend grant policies (configurable), subtree management, project memberships with project-specific roles, org tree, allowed domains
- Projects/modules/screens with duplicate prevention, archive, proposed→approve flow, per-project release config (approval stages, SoD exception, email To/CC roles + extras)
- CR lifecycle: create/draft, BA review actions, manager assignment/reassign, impact analysis, deadline requests with history, confirm assignments, task engine & SIT evidence, automatic CR status, close with acceptance checks, revisions + impact-review flag
- SRN: 6-step wizard, eligibility (SIT-passed tasks/bugs), full vs partial scope, approval stages with SoD, hold/resume, reject/changes, material-change invalidation, revision snapshots, DOCX/PDF generation in supplied template layout, artifacts log
- Deployments: authorize → start → confirm/fail; post-deploy updates, UAT assignments, idempotent SRN email (SENT verified via Resend), thread follow-ups
- UAT board: start, test cases, pass/fail, hold/resume, report bugs, retest; Bug tracker full workflow
- Dashboard (scoped KPIs, filters, pending actions, sections), notifications, global search, reports (current vs historical labels), audit log, Zoho adapter + Sync Now + JSON import + health
- Testing: tests/smoke_flow.py end-to-end pass; testing agent iteration_1 (UI + API) — minor issues fixed (regex escape, page>=1, stale SENDING recovery, follow-up subject, module prefill, stepper, sync toast)

## Backlog
- P0: Connect real Zoho credentials & verify endpoint mappings against the portal
- P1: File attachments via object storage (currently links); PDF attached to SRN email (currently link to release page); MFA for admin (not available in managed auth)
- P1: Native date pickers → shadcn calendar; act-as on mobile
- P2: CI/CD deployment webhook; CReMS→Zoho status writeback; Postgres migration if self-hosting
