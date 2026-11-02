import asyncio
import ipaddress
import os
import re
from datetime import datetime, timedelta, timezone
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from core import db, now, uid, notify, logger, APP_URL

EMAIL_BASE_URL = "https://integrations.emergentagent.com"
EMAIL_KEY = os.environ["EMERGENT_EMAIL_KEY"]
EMAIL_FROM_NAME = os.environ["EMAIL_FROM_NAME"]
MAX_ATTEMPTS = 5

_SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly", "goo.gl", "rebrand.ly")
_CRED_ASK = ("reply with your password", "reply with the code", "send your password", "cvv",
             "send us your password", "enter your password below", "confirm your card number",
             "your full card number", "seed phrase", "recovery phrase", "verify your card",
             "social security number", "confirm your bank details")
_HOSTISH = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I)


def _host_ok(host: str) -> bool:
    if not host or "xn--" in host:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return not any(host == s or host.endswith("." + s) for s in _SHORTENERS)


def _same_site(shown: str, real: str) -> bool:
    return shown == real or real.endswith("." + shown) or shown.endswith("." + real)


class _EmailScan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.urls, self.anchors = set(), [], []
        self._href, self._text = None, []

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag.lower())
        self.urls += [v for k, v in attrs if k.lower() in ("href", "src") and v]
        if tag.lower() == "a":
            self._href = dict((k.lower(), v) for k, v in attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.anchors.append((self._href, "".join(self._text)))
            self._href, self._text = None, []


def _assert_safe_email(subject: str, html: str) -> None:
    scan = _EmailScan()
    scan.feed(html)
    if scan.tags & {"form", "input", "textarea", "select"}:
        raise ValueError("No forms or input fields in email (G2)")
    body = f"{subject}\n{html}".lower()
    for p in _CRED_ASK:
        if p in body:
            raise ValueError(f"Email asks the recipient for credentials: {p!r} (G2)")
    for url in scan.urls:
        low = url.strip().lower()
        if low.startswith(("mailto:", "tel:", "cid:", "#")):
            continue
        if not low.startswith("https://"):
            raise ValueError(f"Email links/assets must be absolute https: {url!r} (G3)")
        host = urlparse(low).hostname or ""
        if not _host_ok(host) or urlparse(low).username is not None:
            raise ValueError(f"Shortened, numeric-host or credential-bearing URL: {url!r} (G3)")
    for href, text in scan.anchors:
        real = urlparse(href.strip().lower()).hostname or ""
        if not real:
            continue
        for m in _HOSTISH.finditer(text):
            if not _same_site(m.group(1).lower(), real):
                raise ValueError(f"Anchor text {m.group(1)!r} ≠ real link host {real!r} (G3)")


async def _send(to, cc, subject, html):
    _assert_safe_email(subject, html)
    payload = {"to": to, "subject": subject, "html": html, "from_name": EMAIL_FROM_NAME}
    if cc:
        payload["cc"] = cc
    if os.environ.get("EMAIL_REPLY_TO"):
        payload["contact_email"] = os.environ["EMAIL_REPLY_TO"]
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{EMAIL_BASE_URL}/api/v1/email/send", headers={"X-Email-Key": EMAIL_KEY}, json=payload)
    if resp.status_code >= 400:
        try:
            j = resp.json()
        except ValueError:
            j = {}
        raise RuntimeError(f"{resp.status_code} {j.get('code', '')} {j.get('message', resp.text[:200])}")
    return resp.json().get("id")


def srn_email_html(srn, project, crs, bugs, deployment, follow_up):
    link = f"{APP_URL}/srns/{srn['id']}"
    cr_rows = "".join(f"<tr><td style='padding:6px;border:1px solid #e2e8f0'>{escape(c['cr_number'])}</td><td style='padding:6px;border:1px solid #e2e8f0'>{escape(c.get('title', ''))}</td><td style='padding:6px;border:1px solid #e2e8f0'>{escape(c.get('module', ''))}</td></tr>" for c in crs)
    bug_rows = "".join(f"<li>{escape(b['number'])} — {escape(b.get('title', ''))}</li>" for b in bugs)
    svc = ", ".join(escape(s.get("name", "")) for s in srn.get("supporting_services", [])) or "—"
    return f"""<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#0f172a">
<h2 style="margin:0 0 4px">{'Follow-up release: ' if follow_up else ''}SRN {escape(srn['number'])} deployed to {escape(deployment.get('environment', 'UAT'))}</h2>
<p style="color:#475569;margin:0 0 16px">Project <b>{escape(project['name'])}</b> · Version <b>{escape(srn.get('release_version', ''))}</b> · Deployed {escape(deployment.get('completed_at', '')[:16].replace('T', ' '))} UTC</p>
<p><b>Release summary</b><br/>{escape(srn.get('summary', '')).replace(chr(10), '<br/>')}</p>
<table style="border-collapse:collapse;font-size:13px"><tr><th style="padding:6px;border:1px solid #e2e8f0;background:#f1f5f9">CR</th><th style="padding:6px;border:1px solid #e2e8f0;background:#f1f5f9">Title</th><th style="padding:6px;border:1px solid #e2e8f0;background:#f1f5f9">Module</th></tr>{cr_rows or '<tr><td colspan=3 style="padding:6px">No CRs</td></tr>'}</table>
<p><b>Bug fixes</b></p><ul>{bug_rows or '<li>None</li>'}</ul>
<p><b>Affected modules:</b> {escape(', '.join(srn.get('impacted_modules', [])) or '—')}<br/><b>Supporting services:</b> {svc}</p>
<p><b>Testing instructions</b><br/>{escape(srn.get('testing_instructions') or srn.get('testing_evidence', '') or 'Please verify the listed CRs and bug fixes.').replace(chr(10), '<br/>')}</p>
<p><a href="{escape(link)}" style="background:#2563eb;color:#fff;padding:10px 16px;border-radius:6px;text-decoration:none">Open release in CReMS</a></p>
<p style="font-size:12px;color:#64748b">The SRN document (PDF/DOCX) is available on the release page. Sent by {escape(EMAIL_FROM_NAME)}.</p>
</td></tr></table>"""


async def queue_email(idem_key, kind, project_id, to, cc, subject, html, srn_id=None, thread_key=None):
    """Idempotent: one message per idempotency key, regardless of retries."""
    if await db.email_messages.find_one({"idempotency_key": idem_key}):
        return None
    thread = None
    if thread_key:
        thread = await db.email_threads.find_one({"key": thread_key}, {"_id": 0})
        if not thread:
            thread = {"id": uid(), "key": thread_key, "project_id": project_id, "subject": subject, "created_at": now()}
            await db.email_threads.insert_one(dict(thread))
        elif not subject.startswith("Re:"):
            subject = "Re: " + thread["subject"]
    m = {"id": uid(), "idempotency_key": idem_key, "kind": kind, "project_id": project_id, "srn_id": srn_id,
         "thread_id": thread["id"] if thread else None, "to": sorted(set(to)), "cc": sorted(set(cc) - set(to)), "subject": subject, "html": html,
         "status": "QUEUED", "attempts": 0, "provider_message_id": None, "last_error": None, "created_at": now(), "next_attempt_at": now()}
    await db.email_messages.insert_one(dict(m))
    return m["id"]


async def process_outbox():
    stale = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
    await db.email_messages.update_many({"status": "SENDING", "sending_at": {"$lt": stale}}, {"$set": {"status": "FAILED", "last_error": "Send interrupted; will retry"}})
    while True:
        m = await db.email_messages.find_one_and_update(
            {"status": {"$in": ["QUEUED", "FAILED"]}, "attempts": {"$lt": MAX_ATTEMPTS}, "next_attempt_at": {"$lte": now()}},
            {"$set": {"status": "SENDING", "sending_at": now()}, "$inc": {"attempts": 1}}, projection={"_id": 0})
        if not m:
            return
        try:
            if not m["to"]:
                raise RuntimeError("No recipients configured")
            pid = await _send(m["to"], m["cc"], m["subject"], m["html"])
            await db.email_messages.update_one({"id": m["id"]}, {"$set": {"status": "SENT", "provider_message_id": pid, "sent_at": now(), "last_error": None}})
            if m.get("thread_id"):
                await db.email_threads.update_one({"id": m["thread_id"]}, {"$push": {"message_ids": pid}})
            await db.audit_logs.insert_one({"id": uid(), "actor_id": "system", "actor_name": "CReMS", "actor_role": "system", "action": "EMAIL_SENT", "entity_type": "srn", "entity_id": m.get("srn_id"), "project_id": m["project_id"], "after": {"to": m["to"], "cc": m["cc"]}, "at": now()})
        except Exception as e:
            backoff = timedelta(seconds=30 * (2 ** m["attempts"]))
            await db.email_messages.update_one({"id": m["id"]}, {"$set": {"status": "FAILED", "last_error": str(e)[:500],
                                                                           "next_attempt_at": (datetime.now(timezone.utc) + backoff).isoformat()}})
            logger.warning(f"Email {m['id']} failed: {e}")
            if m["attempts"] >= MAX_ATTEMPTS and m.get("srn_id"):
                srn = await db.srns.find_one({"id": m["srn_id"]}, {"_id": 0, "author_id": 1, "number": 1})
                await notify([srn["author_id"]], "EMAIL_FAILED", f"SRN email failed for {srn['number']}", f"/srns/{m['srn_id']}", str(e)[:200])


async def deadline_reminders():
    today = datetime.now(timezone.utc).date()
    soon = (today + timedelta(days=2)).isoformat()
    crs = await db.change_requests.find({"status": {"$nin": ["CLOSED", "CANCELLED", "DRAFT", "UAT_PASSED"]}}, {"_id": 0}).to_list(5000)
    for cr in crs:
        dl = cr.get("approved_deadline") or cr.get("requested_deadline")
        if not dl:
            continue
        who = [cr.get("ba_id"), cr.get("manager_id")]
        if dl[:10] < today.isoformat():
            await notify(who, "CR_OVERDUE", f"{cr['number']} is overdue", f"/crs/{cr['id']}", dedupe=f"overdue:{cr['id']}:{today}")
        elif dl[:10] <= soon:
            await notify(who, "DEADLINE_APPROACHING", f"{cr['number']} deadline on {dl[:10]}", f"/crs/{cr['id']}", dedupe=f"soon:{cr['id']}:{dl[:10]}")


async def worker_loop():
    tick = 0
    while True:
        try:
            await process_outbox()
            if tick % 360 == 0:
                await deadline_reminders()
        except Exception as e:
            logger.error(f"worker error: {e}")
        tick += 1
        await asyncio.sleep(10)
