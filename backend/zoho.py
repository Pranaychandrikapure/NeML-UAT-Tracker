import json
import os
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core import db, now, uid, err, audit, notify, current_user, is_admin, next_number, logger

router = APIRouter(prefix="/api")
DEFAULT_CFG = {"dc": "in", "portal_id": "", "cr_entity": "tasks", "cr_match": "CR", "project_ids": [], "default_ba_email": ""}


def _creds():
    return {k: os.environ.get(k, "") for k in ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN")}


async def _cfg():
    c = await db.zoho_integrations.find_one({"id": "default"}, {"_id": 0})
    cfg = {**DEFAULT_CFG, **(c or {})}
    if not cfg["portal_id"]:
        cfg["portal_id"] = os.environ.get("ZOHO_PORTAL_ID", "")
    if not (c or {}).get("dc") and os.environ.get("ZOHO_DC"):
        cfg["dc"] = os.environ["ZOHO_DC"]
    return cfg


SYSTEM_USER = {"id": "system", "name": "Zoho Auto Sync", "role": "system_admin"}


async def auto_sync():
    """Scheduled sync; only runs when credentials and portal are configured."""
    cfg = await _cfg()
    if all(_creds().values()) and cfg["portal_id"] and cfg.get("auto_sync", True):
        await run_sync(SYSTEM_USER)


def _date(v):
    if not v:
        return None
    for fmt in ("%m-%d-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(v[:10], fmt).date().isoformat()
        except ValueError:
            continue
    return None


async def upsert_project(ext_id, name, desc, owner_name, owner_email, status, start, end, raw, job_id):
    existing = await db.projects.find_one({"zoho_id": ext_id}, {"_id": 0})
    fields = {"name": name, "description": desc or "", "owner_name": owner_name or "", "owner_email": owner_email or "",
              "status": status or "Active", "start_date": start, "end_date": end, "raw": raw, "synced_at": now()}
    if existing:
        await db.projects.update_one({"id": existing["id"]}, {"$set": fields})
        return existing["id"], False
    from core import DEFAULT_PROJECT_CONFIG
    pid = uid()
    code = "".join(ch for ch in name.upper() if ch.isalnum())[:8] + "-" + ext_id[-4:]
    await db.projects.insert_one({**fields, "id": pid, "zoho_id": ext_id, "code": code, "source": "ZOHO", "tech_stack": [],
                                  "config": DEFAULT_PROJECT_CONFIG, "created_at": now(), "updated_at": now(), "sync_job_id": job_id})
    if owner_email:
        owner = await db.users.find_one({"email": owner_email.lower()}, {"_id": 0})
        if owner and owner["role"] != "system_admin":
            await db.project_members.update_one({"project_id": pid, "user_id": owner["id"]}, {"$setOnInsert": {"project_role": owner["role"], "at": now()}}, upsert=True)
    return pid, True


async def upsert_cr(project_id, ext_id, title, desc, priority, deadline, raw, default_ba, job):
    existing = await db.change_requests.find_one({"source": "ZOHO", "external_id": ext_id}, {"_id": 0})
    if existing:
        changed = {k: v for k, v in {"title": title, "description": desc}.items() if v and existing.get(k) != v}
        if changed:
            sets = {**changed, "external_raw": raw, "revision": existing.get("revision", 1) + 1}
            if existing["status"] not in ("DRAFT", "NEW", "BA_REVIEW"):
                sets["needs_impact_review"] = True
                await notify([existing.get("ba_id"), existing.get("manager_id")], "CR_IMPACT_REVIEW", f"{existing['number']} changed in Zoho — impact review", f"/crs/{existing['id']}")
            await db.change_requests.update_one({"id": existing["id"]}, {"$set": sets})
            await db.cr_revisions.insert_one({"id": uid(), "cr_id": existing["id"], "revision": sets["revision"], "snapshot": changed, "changed": list(changed), "by": "zoho-sync", "at": now()})
            job["updated"] += 1
        return
    num = await next_number("CR")
    cr = {"id": uid(), "number": num, "title": title, "project_id": project_id, "source": "ZOHO", "external_id": ext_id, "external_raw": raw,
          "description": desc or "", "business_requirements": "", "expected_result": "", "justification": "", "priority": priority or "Medium",
          "requested_deadline": deadline, "approved_deadline": None, "business_owner": "", "ba_id": default_ba, "manager_id": None,
          "impacted_module_ids": [], "impacted_screen_ids": [], "acceptance_criteria": "", "attachments": [], "impact": {}, "status": "NEW",
          "revision": 1, "created_by": "zoho-sync", "created_by_name": "Zoho Sync", "created_at": now(), "updated_at": now(), "version": 1,
          "comments": [], "status_history": [{"from": None, "to": "NEW", "by": "zoho-sync", "by_name": "Zoho Sync", "at": now()}]}
    await db.change_requests.insert_one(cr)
    job["created"] += 1
    await notify([default_ba], "CR_BA_VALIDATION", f"New Zoho CR {num} requires validation", f"/crs/{cr['id']}")


async def run_sync(u):
    cfg, creds = await _cfg(), _creds()
    job = {"id": uid(), "started_at": now(), "status": "RUNNING", "by": u["name"], "projects": 0, "created": 0, "updated": 0, "errors": []}
    await db.zoho_sync_jobs.insert_one(dict(job))
    try:
        if not all(creds.values()) or not cfg["portal_id"]:
            raise RuntimeError("Zoho is not configured: add ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN and portal ID")
        dc = cfg["dc"]
        async with httpx.AsyncClient(timeout=30) as c:
            tr = await c.post(f"https://accounts.zoho.{dc}/oauth/v2/token", params={"refresh_token": creds["ZOHO_REFRESH_TOKEN"], "client_id": creds["ZOHO_CLIENT_ID"],
                                                                                   "client_secret": creds["ZOHO_CLIENT_SECRET"], "grant_type": "refresh_token"})
            token = tr.json().get("access_token")
            if not token:
                raise RuntimeError(f"Token refresh failed: {tr.text[:200]}")
            h = {"Authorization": f"Zoho-oauthtoken {token}"}
            base = f"https://projectsapi.zoho.{dc}/restapi/portal/{cfg['portal_id']}"
            last = (await db.zoho_integrations.find_one({"id": "default"}, {"_id": 0}) or {}).get("last_success_at")
            ba = await db.users.find_one({"email": (cfg.get("default_ba_email") or "").lower()}, {"_id": 0, "id": 1})
            idx = 1
            while True:
                r = await c.get(f"{base}/projects/", headers=h, params={"index": idx, "range": 100})
                if r.status_code == 204:
                    break
                r.raise_for_status()
                projs = r.json().get("projects", [])
                for p in projs:
                    if cfg["project_ids"] and p["id_string"] not in cfg["project_ids"]:
                        continue
                    pid, _ = await upsert_project(p["id_string"], p["name"], p.get("description"), p.get("owner_name"), p.get("owner_email"),
                                                  p.get("status"), _date(p.get("start_date")), _date(p.get("end_date")), p, job["id"])
                    job["projects"] += 1
                    ti = 1
                    while True:
                        params = {"index": ti, "range": 100}
                        if last:
                            params["last_modified_time"] = last[:19]
                        rr = await c.get(f"{base}/projects/{p['id_string']}/{cfg['cr_entity']}/", headers=h, params=params)
                        if rr.status_code == 204:
                            break
                        rr.raise_for_status()
                        recs = rr.json().get(cfg["cr_entity"], [])
                        for t in recs:
                            name = t.get("name") or t.get("title") or ""
                            tl = (t.get("tasklist") or {}).get("name", "")
                            if cfg["cr_match"] and cfg["cr_match"].lower() not in (name + " " + tl + " " + t.get("key", "")).lower():
                                continue
                            await upsert_cr(pid, f"{cfg['cr_entity']}:{t['id_string']}", name, t.get("description"), t.get("priority"),
                                            _date(t.get("end_date") or t.get("due_date")), t, ba["id"] if ba else None, job)
                        if len(recs) < 100:
                            break
                        ti += 100
                if len(projs) < 100:
                    break
                idx += 100
        job["status"] = "SUCCESS"
        await db.zoho_integrations.update_one({"id": "default"}, {"$set": {"last_success_at": now()}}, upsert=True)
    except Exception as e:
        job["status"] = "FAILED"
        job["errors"].append(str(e)[:500])
        logger.warning(f"Zoho sync failed: {e}")
    job["finished_at"] = now()
    await db.zoho_sync_jobs.update_one({"id": job["id"]}, {"$set": job})
    await audit(u, "ZOHO_SYNC", "integration", "zoho", None, None, {k: job[k] for k in ("status", "projects", "created", "updated")})
    return job


def _admin(u):
    if not is_admin(u):
        err(403, "Admin only")


@router.get("/integrations/zoho")
async def zoho_status(u=Depends(current_user)):
    _admin(u)
    cfg = await _cfg()
    creds = _creds()
    jobs = await db.zoho_sync_jobs.find({}, {"_id": 0}).sort("started_at", -1).to_list(20)
    return {"config": cfg, "credentials_present": {k: bool(v) for k, v in creds.items()},
            "connected": all(creds.values()) and bool(cfg["portal_id"]), "jobs": jobs,
            "zoho_projects": await db.projects.count_documents({"source": "ZOHO"}), "zoho_crs": await db.change_requests.count_documents({"source": "ZOHO"})}


class ZohoCfg(BaseModel):
    dc: str = "in"
    portal_id: str = ""
    cr_entity: str = "tasks"
    cr_match: str = "CR"
    project_ids: list = []
    default_ba_email: str = ""
    auto_sync: bool = True


@router.put("/integrations/zoho")
async def zoho_config(body: ZohoCfg, u=Depends(current_user)):
    _admin(u)
    if body.cr_entity not in ("tasks", "bugs"):
        err(400, "CR entity must be tasks or bugs")
    await db.zoho_integrations.update_one({"id": "default"}, {"$set": body.model_dump()}, upsert=True)
    await audit(u, "ZOHO_CONFIG_UPDATED", "integration", "zoho", None, None, body.model_dump())
    return {"ok": True}


@router.post("/integrations/zoho/sync")
async def zoho_sync(u=Depends(current_user)):
    _admin(u)
    return await run_sync(u)


class ImportIn(BaseModel):
    payload: str


def _walk_owner(obj):
    if isinstance(obj, dict):
        if obj.get("email") and (obj.get("zpuid") or obj.get("zuid")):
            return obj
        for v in obj.values():
            r = _walk_owner(v)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _walk_owner(v)
            if r:
                return r
    return None


@router.post("/integrations/zoho/import")
async def zoho_import(body: ImportIn, u=Depends(current_user)):
    """Import a Zoho Projects list-view JSON export (project-level data only)."""
    _admin(u)
    try:
        data = json.loads(body.payload)
    except ValueError:
        err(400, "Invalid JSON")
    job = {"id": uid(), "started_at": now(), "status": "RUNNING", "by": u["name"], "projects": 0, "created": 0, "updated": 0, "errors": [], "kind": "IMPORT"}
    for grp in data.get("data", []):
        for e in grp.get("entities", []):
            dates, status, owner = [], None, None
            for cell in (e.get("cells") or {}).values():
                d = cell.get("data")
                if isinstance(d, str) and _date(d):
                    dates.append(_date(d))
                elif isinstance(d, dict) and "display_value" in d:
                    status = d["display_value"]
                elif isinstance(d, dict) and "image_url" in d:
                    owner = d.get("name")
            o = _walk_owner(e) or {}
            _, created = await upsert_project(e["id"], e["name"], "", owner or o.get("display_name"), o.get("email"), status,
                                              dates[0] if dates else None, dates[1] if len(dates) > 1 else None, {"entity_id": e["id"]}, job["id"])
            job["projects"] += 1
            job["created" if created else "updated"] += 1
    job.update({"status": "SUCCESS", "finished_at": now()})
    await db.zoho_sync_jobs.insert_one(dict(job))
    await audit(u, "ZOHO_IMPORT", "integration", "zoho", None, None, {"projects": job["projects"]})
    job.pop("_id", None)
    return job
