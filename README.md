# CReMS — Change & Release Management System

## Stack (platform constraints)
React (CRA) + Tailwind + shadcn/ui + TanStack Query + Recharts · FastAPI · MongoDB · Emergent-managed Clerk auth (Google + email/password) · Emergent-managed Resend email.
(Next.js / PostgreSQL / Redis / Celery were requested but cannot run on this platform; equivalent logic is implemented as a modular monolith with an in-process background worker.)

## Backend layout (`/app/backend`)
- `core.py` – DB, roles, grant defaults, auth (`current_user`, demo act-as), project scoping, audit, notifications, guarded (concurrency-safe) transitions
- `workflow.py` – CR status engine (`recompute_cr`) derived from tasks + blocking bugs
- `routes_org.py` – me, users, org tree, grant policies, projects, members, modules, screens, tech master data
- `routes_cr.py` – CRs, BA review actions, impact analysis, deadline negotiation, tasks + SIT
- `routes_release.py` – SRNs, approval stages + segregation of duties, revisions, DOCX/PDF, deployments, email queueing
- `routes_uat.py` – UAT assignments, test cases, holds, bugs workflow
- `routes_dash.py` – dashboard KPIs/pending actions, notifications, audit, search, reports
- `zoho.py` – Zoho Projects OAuth sync adapter, config, health, JSON import
- `emailer.py` – idempotent outbox worker (retries/backoff, thread tracking), deadline reminders
- `srn_doc.py` – SRN DOCX/PDF generation following the supplied SRN template
- `seed.py` – indexes, tech master data, admin record, demo data (DEMO_MODE=true)

## Environment (`backend/.env`)
MONGO_URL, DB_NAME, CORS_ORIGINS, CLERK_* (platform-managed), ADMIN_EMAIL, EMERGENT_EMAIL_KEY, EMAIL_FROM_NAME, APP_URL, DEMO_MODE.
Zoho (not configured yet): ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN + portal ID in Administration → Zoho.
Set DEMO_MODE=false for production to disable demo seed and act-as.

## Tests
- `tests/smoke_flow.py` – full end-to-end lifecycle (requires fresh demo seed; reset with `tests/reset_demo_data.py` + backend restart).
