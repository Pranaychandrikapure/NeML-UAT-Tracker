import os
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument
from starlette.concurrency import run_in_threadpool

load_dotenv(Path(__file__).parent / ".env")
try:
    from backend.clerk_auth import require_user
except ModuleNotFoundError:
    from clerk_auth import require_user

client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]
logger = logging.getLogger("crems")
DEMO_MODE = os.environ.get("DEMO_MODE", "false").lower() == "true"
APP_URL = os.environ.get("APP_URL", "")

ROLES = {
    "system_admin": {"label": "System Admin", "branch": "root"},
    "project_lead": {"label": "Project Lead", "branch": "dev"},
    "senior_pm": {"label": "Senior Project Manager", "branch": "dev"},
    "pm": {"label": "Project Manager", "branch": "dev"},
    "team_lead": {"label": "Team Lead", "branch": "dev"},
    "developer": {"label": "Developer", "branch": "dev"},
    "ba_lead": {"label": "BA Lead", "branch": "ba"},
    "ba": {"label": "Business Analyst", "branch": "ba"},
    "uat_lead": {"label": "UAT Lead", "branch": "uat"},
    "uat_manager": {"label": "UAT Manager", "branch": "uat"},
    "uat_member": {"label": "UAT Member", "branch": "uat"},
}
DEFAULT_GRANTS = {
    "system_admin": list(ROLES.keys()),
    "project_lead": ["senior_pm"],
    "senior_pm": ["pm", "team_lead", "developer"],
    "pm": ["team_lead", "developer"],
    "team_lead": [],
    "ba_lead": ["ba"],
    "uat_lead": ["uat_manager"],
    "uat_manager": ["uat_member"],
}
MANAGERS = {"project_lead", "senior_pm", "pm", "team_lead"}
DEV_EXEC = {"pm", "team_lead", "developer", "senior_pm"}
BA_ROLES = {"ba", "ba_lead"}
UAT_ROLES = {"uat_lead", "uat_manager", "uat_member"}
DEFAULT_TECH = ["Java", "Spring Boot", "Python", "FastAPI", "Next.js", "React", "Angular",
                "PostgreSQL", "MySQL", "MongoDB", "Redis", "Docker", "Kubernetes", "Node.js"]
DEFAULT_PROJECT_CONFIG = {
    "approval_stages": [
        {"key": "TECH", "label": "Team Lead & PM Review", "roles": ["team_lead", "pm"], "all_roles": True},
        {"key": "BA", "label": "BA Approval", "roles": ["ba", "ba_lead"], "all_roles": False},
        {"key": "UAT", "label": "UAT Approval", "roles": ["uat_lead", "uat_manager"], "all_roles": False},
    ],
    "allow_self_approval": False,
    "email_to_roles": ["uat_lead", "uat_manager", "uat_member"],
    "email_cc_roles": ["ba", "pm", "team_lead"],
    "email_extra_to": [],
    "email_extra_cc": [],
    "require_module_approval": True,
}


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return str(uuid.uuid4())


def err(code, msg):
    raise HTTPException(status_code=code, detail=msg)


async def next_number(prefix):
    year = datetime.now(timezone.utc).year
    c = await db.counters.find_one_and_update({"_id": f"{prefix}-{year}"}, {"$inc": {"seq": 1}},
                                              upsert=True, return_document=ReturnDocument.AFTER)
    return f"{prefix}-{year}-{c['seq']:04d}"


async def get_setting(key, default):
    s = await db.settings.find_one({"key": key}, {"_id": 0})
    return s["value"] if s else default


def _clerk_emails(clerk_id):
    r = requests.get(f"https://api.clerk.com/v1/users/{clerk_id}", timeout=10,
                     headers={"Authorization": f"Bearer {os.environ['CLERK_SECRET_KEY']}", "User-Agent": "crems-app"})
    r.raise_for_status()
    data = r.json()
    emails = [e["email_address"].lower() for e in data.get("email_addresses", [])
              if (e.get("verification") or {}).get("status") == "verified"]
    name = " ".join(x for x in [data.get("first_name"), data.get("last_name")] if x)
    return emails, name


async def _resolve_user(clerk_id):
    u = await db.users.find_one({"clerk_id": clerk_id}, {"_id": 0})
    if u:
        return u
    emails, name = await run_in_threadpool(_clerk_emails, clerk_id)
    u = await db.users.find_one({"email": {"$in": emails}}, {"_id": 0})
    admins = {e.strip().lower() for e in os.environ.get("ADMIN_EMAIL", "").split(",") if e.strip()}
    if not u and set(emails) & admins:
        email = sorted(set(emails) & admins)[0]
        u = {"id": uid(), "email": email, "name": name or email.split("@")[0], "role": "system_admin",
             "reporting_manager_id": None, "department": "Administration", "active": True,
             "is_demo": False, "created_at": now(), "notify_email": True}
        await db.users.insert_one(dict(u))
    if not u:
        err(403, "NOT_PROVISIONED")
    await db.users.update_one({"id": u["id"]}, {"$set": {"clerk_id": clerk_id, "last_login": now()}})
    await db.audit_logs.insert_one({"id": uid(), "actor_id": u["id"], "actor_name": u["name"], "actor_role": u["role"],
                                    "action": "LOGIN", "entity_type": "user", "entity_id": u["id"], "at": now()})
    return u


async def current_user(request: Request, claims: dict = Depends(require_user)) -> dict:
    u = await _resolve_user(claims["user_id"])
    if not u.get("active", True):
        err(403, "ACCOUNT_INACTIVE")
    act_as = request.headers.get("x-act-as")
    if act_as and act_as != u["id"]:
        if not (DEMO_MODE and u["role"] == "system_admin"):
            err(403, "Act-as not permitted")
        t = await db.users.find_one({"id": act_as, "is_demo": True, "active": True}, {"_id": 0})
        if not t:
            err(403, "Act-as is limited to active demo users")
        t["real_user_id"] = u["id"]
        return t
    return u


def is_admin(u):
    return u["role"] == "system_admin"


async def my_project_ids(u):
    if is_admin(u):
        return None
    return await db.project_members.distinct("project_id", {"user_id": u["id"]})


def pscope(pids, field="project_id"):
    return {} if pids is None else {field: {"$in": pids}}


async def member_role(u, project_id):
    m = await db.project_members.find_one({"project_id": project_id, "user_id": u["id"]}, {"_id": 0})
    return m["project_role"] if m else None


async def require_project(u, project_id, roles=None):
    """Return the caller's project role; 404 if no access, 403 if role not allowed."""
    if is_admin(u):
        return "system_admin"
    pr = await member_role(u, project_id)
    if not pr:
        err(404, "Project not found")
    if roles and pr not in roles and u["role"] not in roles:
        err(403, "Your project role does not permit this action")
    return pr


async def audit(u, action, etype, eid, project_id=None, before=None, after=None, comment=None, meta=None):
    await db.audit_logs.insert_one({
        "id": uid(), "actor_id": u["id"], "actor_name": u["name"], "actor_role": u["role"],
        "real_user_id": u.get("real_user_id"), "action": action, "entity_type": etype, "entity_id": eid,
        "project_id": project_id, "before": before, "after": after, "comment": comment, "meta": meta,
        "correlation_id": uid(), "at": now()})


async def notify(user_ids, event, title, link, body="", dedupe=None):
    for user_id in {x for x in user_ids if x}:
        key = f"{dedupe}:{user_id}" if dedupe else None
        if key and await db.notifications.find_one({"dedupe": key}):
            continue
        await db.notifications.insert_one({"id": uid(), "user_id": user_id, "event": event, "title": title,
                                           "body": body, "link": link, "read": False, "dedupe": key, "at": now()})


async def project_users(project_id, roles):
    ms = await db.project_members.find({"project_id": project_id, "project_role": {"$in": list(roles)}},
                                       {"_id": 0}).to_list(500)
    return [m["user_id"] for m in ms]


async def guarded(coll, _id, from_status, set_fields, push=None):
    """Concurrency-safe transition: only applies if the record is still in an allowed source status."""
    q = {"id": _id}
    if from_status is not None:
        q["status"] = {"$in": list(from_status)}
    upd = {"$set": {**set_fields, "updated_at": now()}, "$inc": {"row_version": 1}}
    if push:
        upd["$push"] = push
    doc = await db[coll].find_one_and_update(q, upd, projection={"_id": 0}, return_document=ReturnDocument.AFTER)
    if not doc:
        err(409, "This record changed or is not in a valid state for this action. Refresh and retry.")
    return doc


async def users_map(ids):
    us = await db.users.find({"id": {"$in": list({i for i in ids if i})}}, {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1}).to_list(2000)
    return {x["id"]: x for x in us}
