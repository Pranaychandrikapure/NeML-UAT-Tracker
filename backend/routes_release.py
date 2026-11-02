from typing import List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel

from core import (db, now, uid, err, audit, notify, guarded, current_user, my_project_ids, pscope, require_project,
                  next_number, project_users, users_map, is_admin, ROLES, DEV_EXEC, MANAGERS, DEFAULT_PROJECT_CONFIG)
from workflow import set_cr_status, recompute_cr
from srn_doc import srn_context, build_docx, build_pdf
from emailer import queue_email, srn_email_html

router = APIRouter(prefix="/api")
MATERIAL = ["items", "bug_ids", "release_version", "deployment_instructions", "rollback_instructions", "supporting_services", "tech_stack", "summary"]
EDITABLE = {"DRAFT", "REJECTED", "CHANGES_REQUESTED", "IN_REVIEW", "ON_HOLD"}


class ItemIn(BaseModel):
    cr_id: str
    task_ids: List[str] = []
    description: str = ""
    impact: str = "Yes"


class SRNIn(BaseModel):
    project_id: str
    application_name: str = ""
    company_name: str = ""
    team_name: str = ""
    release_version: str
    intended_prod_version: str = ""
    release_type: str = "Final"
    release_date: Optional[str] = None
    environment: str = "UAT"
    tech_stack: List[str] = []
    impacted_modules: List[str] = []
    impacted_screens: List[str] = []
    supporting_services: List[dict] = []
    items: List[ItemIn] = []
    bug_ids: List[str] = []
    description: str = ""
    summary: str = ""
    impact_details: str = ""
    testing_evidence: str = ""
    testing_instructions: str = ""
    deployment_instructions: str = ""
    rollback_instructions: str = ""
    build_ref: str = ""
    attachments: List[dict] = []


class DecisionIn(BaseModel):
    decision: str
    comment: Optional[str] = None
    hold_reason: Optional[str] = None
    responsible_id: Optional[str] = None
    expected_date: Optional[str] = None


class DeployIn(BaseModel):
    success: Optional[bool] = None
    build_id: str = ""
    notes: str = ""
    failure_details: str = ""
    rollback_result: str = ""
    environment: str = "UAT"


async def eligible(project_id, srn_id=None):
    ok_srn = [None] + ([srn_id] if srn_id else [])
    tasks = await db.cr_tasks.find({"project_id": project_id, "status": "SIT_PASSED", "srn_id": {"$in": ok_srn}}, {"_id": 0}).to_list(2000)
    by_cr = {}
    for t in tasks:
        by_cr.setdefault(t["cr_id"], []).append(t)
    crs = []
    for cr_id, ts in by_cr.items():
        cr = await db.change_requests.find_one({"id": cr_id}, {"_id": 0, "status_history": 0, "comments": 0})
        if cr["status"] in ("CANCELLED", "CLOSED"):
            continue
        remaining = await db.cr_tasks.count_documents({"cr_id": cr_id, "status": {"$nin": ["SIT_PASSED", "READY_FOR_UAT", "CANCELLED"]}, "mandatory": {"$ne": False}})
        mod_ids = [t.get("module_id") for t in ts if t.get("module_id")] or cr.get("impacted_module_ids", [])
        mods = await db.modules.find({"id": {"$in": mod_ids}}, {"_id": 0, "name": 1}).to_list(50)
        crs.append({"cr_id": cr_id, "cr_number": cr["number"], "title": cr["title"], "status": cr["status"],
                    "full_possible": remaining == 0 and cr["status"] in ("READY_FOR_UAT", "RELEASE_APPROVAL_PENDING"),
                    "remaining_tasks": remaining, "module": ", ".join(m["name"] for m in mods),
                    "tasks": [{"id": t["id"], "number": t["number"], "title": t["title"]} for t in ts]})
    bugs = await db.bugs.find({"project_id": project_id, "$or": [{"status": "SIT_PASSED", "srn_id": None}, {"srn_id": srn_id or "__none__"}]}, {"_id": 0}).to_list(500)
    return {"crs": crs, "bugs": bugs}


@router.get("/srns/eligible")
async def get_eligible(project_id: str, u=Depends(current_user)):
    await require_project(u, project_id)
    return await eligible(project_id)


async def _build_items(body, srn_id=None):
    el = await eligible(body.project_id, srn_id)
    em = {c["cr_id"]: c for c in el["crs"]}
    items = []
    for it in body.items:
        c = em.get(it.cr_id)
        if not c:
            err(400, "Selected CR has no SIT-passed tasks eligible for release")
        allowed = {t["id"] for t in c["tasks"]}
        tids = it.task_ids or list(allowed)
        if not set(tids) <= allowed:
            err(400, f"{c['cr_number']}: only SIT-passed, unreleased tasks can be included")
        scope = "full" if c["full_possible"] and set(tids) == allowed else "partial"
        items.append({"cr_id": it.cr_id, "cr_number": c["cr_number"], "title": c["title"], "task_ids": tids, "scope": scope,
                      "module": c["module"], "description": it.description or c["title"], "impact": it.impact})
    bm = {b["id"]: b for b in el["bugs"]}
    for b in body.bug_ids:
        if b not in bm:
            err(400, "Only SIT-passed bug fixes can be included")
    bug_items = [{"id": b, "number": bm[b]["number"], "title": bm[b]["title"], "cr_id": bm[b].get("cr_id"), "fix_notes": bm[b].get("fix_notes", ""), "module": ""} for b in body.bug_ids]
    if not items and not bug_items:
        err(400, "Select at least one CR or bug fix")
    return items, bug_items


async def _can_initiate(u, project_id):
    pr = await require_project(u, project_id)
    if not (is_admin(u) or pr in DEV_EXEC or pr in MANAGERS):
        err(403, "Only developers / development managers can create SRNs")
    return pr


@router.post("/srns")
async def create_srn(body: SRNIn, u=Depends(current_user)):
    await _can_initiate(u, body.project_id)
    items, bug_items = await _build_items(body)
    proj = await db.projects.find_one({"id": body.project_id}, {"_id": 0})
    s = {**body.model_dump(exclude={"items"}), "items": items, "bug_items": bug_items, "id": uid(), "number": await next_number("SRN"),
         "application_name": body.application_name or proj["name"], "author_id": u["id"], "author_name": u["name"],
         "status": "DRAFT", "revision": 1, "current_stage": 0, "hold": None, "created_at": now(), "updated_at": now(), "version": 1}
    await db.srns.insert_one(dict(s))
    await db.srn_revisions.insert_one({"id": uid(), "srn_id": s["id"], "revision": 1, "snapshot": {k: s.get(k) for k in MATERIAL}, "by": u["id"], "at": now()})
    await audit(u, "SRN_CREATED", "srn", s["id"], body.project_id, None, {"number": s["number"], "items": [i["cr_number"] for i in items]})
    s.pop("_id", None)
    return s


@router.patch("/srns/{sid}")
async def edit_srn(sid: str, body: SRNIn, u=Depends(current_user)):
    s = await load_srn(u, sid)
    if u["id"] != s["author_id"] and not is_admin(u):
        err(403, "Only the SRN author can edit")
    if s["status"] not in EDITABLE:
        err(409, f"SRN cannot be edited in {s['status']}")
    items, bug_items = await _build_items(body, sid)
    new = {**body.model_dump(exclude={"items", "project_id"}), "items": items, "bug_items": bug_items}
    material = any(new.get(k) != s.get(k) for k in MATERIAL)
    sets = dict(new)
    if material and s["status"] in ("IN_REVIEW", "ON_HOLD"):
        await db.srn_approvals.update_many({"srn_id": sid, "valid": True}, {"$set": {"valid": False, "invalidated_at": now(), "invalidated_reason": "Material change"}})
        await _release_scope(s, u, back=True)
        sets.update({"status": "CHANGES_REQUESTED", "current_stage": 0})
    if material:
        sets["revision"] = s["revision"] + 1
        await db.srn_revisions.insert_one({"id": uid(), "srn_id": sid, "revision": sets["revision"], "snapshot": {k: new.get(k) for k in MATERIAL}, "by": u["id"], "at": now()})
    s2 = await guarded("srns", sid, [s["status"]], sets)
    await audit(u, "SRN_MODIFIED", "srn", sid, s["project_id"], None, {"material": material, "revision": s2["revision"]})
    return s2


async def load_srn(u, sid):
    s = await db.srns.find_one({"id": sid}, {"_id": 0})
    if not s:
        err(404, "SRN not found")
    await require_project(u, s["project_id"])
    return s


async def _config(project_id):
    p = await db.projects.find_one({"id": project_id}, {"_id": 0, "config": 1})
    return {**DEFAULT_PROJECT_CONFIG, **(p.get("config") or {})}


async def _required_roles(project_id, stage):
    if not stage.get("all_roles"):
        return None
    present = await db.project_members.distinct("project_role", {"project_id": project_id, "project_role": {"$in": stage["roles"]}})
    return [r for r in stage["roles"] if r in present]


async def can_approve(u, s, cfg=None):
    """Return (ok, reason, role) for the caller on the SRN's current stage."""
    if s["status"] != "IN_REVIEW":
        return False, "SRN is not in review", None
    cfg = cfg or await _config(s["project_id"])
    stage = cfg["approval_stages"][s["current_stage"]]
    m = await db.project_members.find_one({"project_id": s["project_id"], "user_id": u["id"]}, {"_id": 0})
    role = m["project_role"] if m else None
    if role not in stage["roles"]:
        return False, f"Stage '{stage['label']}' needs {', '.join(ROLES[r]['label'] for r in stage['roles'])}", None
    if not cfg.get("allow_self_approval"):
        if u["id"] == s["author_id"]:
            return False, "Segregation of duties: authors cannot approve their own SRN", role
        devs = await db.cr_tasks.distinct("developer_id", {"id": {"$in": [t for i in s["items"] for t in i["task_ids"]]}})
        bug_devs = await db.bugs.distinct("developer_id", {"id": {"$in": s.get("bug_ids", [])}})
        if u["id"] in devs or u["id"] in bug_devs:
            return False, "Segregation of duties: you developed work in this release", role
    done = await db.srn_approvals.find({"srn_id": s["id"], "stage": stage["key"], "valid": True, "decision": "APPROVE"}, {"_id": 0}).to_list(50)
    if any(a["approver_id"] == u["id"] for a in done):
        return False, "You already approved this stage", role
    req = await _required_roles(s["project_id"], stage)
    if req is not None and role in {a["role"] for a in done}:
        return False, "This role has already approved the stage", role
    return True, "", role


async def _stage_complete(s, stage):
    done = await db.srn_approvals.find({"srn_id": s["id"], "stage": stage["key"], "valid": True, "decision": "APPROVE"}, {"_id": 0}).to_list(50)
    req = await _required_roles(s["project_id"], stage)
    if req is None:
        return len(done) > 0
    return set(req) <= {a["role"] for a in done}


async def _stage_approvers(s, cfg):
    stage = cfg["approval_stages"][s["current_stage"]]
    return await project_users(s["project_id"], set(stage["roles"]))


async def _release_scope(s, u, back):
    """Mark or unmark tasks/bugs/CRs as being in this release's approval scope."""
    tids = [t for i in s["items"] for t in i["task_ids"]]
    if back:
        await db.cr_tasks.update_many({"id": {"$in": tids}, "srn_id": s["id"]}, {"$set": {"srn_id": None}})
        await db.bugs.update_many({"id": {"$in": s.get("bug_ids", [])}, "srn_id": s["id"]}, {"$set": {"srn_id": None, "status": "SIT_PASSED"}})
        for it in s["items"]:
            cr = await db.change_requests.find_one({"id": it["cr_id"]}, {"_id": 0})
            if cr["status"] in ("RELEASE_APPROVAL_PENDING", "UAT_DEPLOYMENT_PENDING"):
                await set_cr_status(cr, "READY_FOR_UAT", u, f"SRN {s['number']} returned")
                await recompute_cr(cr["id"], u)
    else:
        await db.cr_tasks.update_many({"id": {"$in": tids}}, {"$set": {"srn_id": s["id"]}})
        await db.bugs.update_many({"id": {"$in": s.get("bug_ids", [])}}, {"$set": {"srn_id": s["id"], "status": "FIXED_AWAITING_RELEASE"}})
        for it in s["items"]:
            if it["scope"] == "full":
                cr = await db.change_requests.find_one({"id": it["cr_id"]}, {"_id": 0})
                if cr["status"] == "READY_FOR_UAT":
                    await set_cr_status(cr, "RELEASE_APPROVAL_PENDING", u, f"Included in SRN {s['number']}")


@router.post("/srns/{sid}/submit")
async def submit_srn(sid: str, u=Depends(current_user)):
    s = await load_srn(u, sid)
    if u["id"] != s["author_id"]:
        err(403, "Only the author can submit")
    if s["status"] not in ("DRAFT", "REJECTED", "CHANGES_REQUESTED"):
        err(409, "SRN already submitted")
    body = SRNIn(**{**s, "items": [ItemIn(cr_id=i["cr_id"], task_ids=i["task_ids"], description=i["description"], impact=i["impact"]) for i in s["items"]]})
    items, bug_items = await _build_items(body, sid)
    s = await guarded("srns", sid, [s["status"]], {"status": "IN_REVIEW", "current_stage": 0, "items": items, "bug_items": bug_items, "submitted_at": now(), "hold": None})
    await _release_scope(s, u, back=False)
    cfg = await _config(s["project_id"])
    await audit(u, "SRN_SUBMITTED", "srn", sid, s["project_id"], None, {"revision": s["revision"]})
    await notify(await _stage_approvers(s, cfg), "SRN_APPROVAL_REQUESTED", f"SRN {s['number']} awaits your approval", f"/srns/{sid}", dedupe=f"srn:{sid}:r{s['revision']}:s0")
    return s


@router.post("/srns/{sid}/decision")
async def decide_srn(sid: str, body: DecisionIn, u=Depends(current_user)):
    s = await load_srn(u, sid)
    cfg = await _config(s["project_id"])
    d = body.decision
    if d not in ("APPROVE", "REJECT", "REQUEST_CHANGES", "HOLD", "RESUME"):
        err(400, "Invalid decision")
    link = f"/srns/{sid}"
    before = s["status"]
    if d == "RESUME":
        if s["status"] != "ON_HOLD":
            err(409, "SRN is not on hold")
        hold = s.get("hold") or {}
        if u["id"] not in (hold.get("by"), hold.get("responsible_id")) and not is_admin(u):
            err(403, "Only the hold owner or responsible user can resume")
        s2 = await guarded("srns", sid, ["ON_HOLD"], {"status": "IN_REVIEW", "hold": {**hold, "resolved_at": now(), "resolved_by": u["name"]}})
        role = hold.get("role")
        stage_key = hold.get("stage")
    else:
        ok, reason, role = await can_approve(u, s, cfg)
        if not ok:
            err(403, reason)
        stage = cfg["approval_stages"][s["current_stage"]]
        stage_key = stage["key"]
        if d in ("REJECT", "REQUEST_CHANGES") and not body.comment:
            err(400, "Comments are required")
        if d == "HOLD" and not (body.hold_reason and body.responsible_id and body.expected_date):
            err(400, "Hold reason, responsible user and expected resolution date are required")
        if d == "APPROVE":
            await db.srn_approvals.insert_one({"id": uid(), "srn_id": sid, "stage": stage_key, "stage_label": stage["label"], "revision": s["revision"],
                                               "approver_id": u["id"], "approver_name": u["name"], "role": role, "role_label": ROLES[role]["label"],
                                               "decision": d, "comment": body.comment, "before": before, "valid": True, "at": now()})
            if await _stage_complete(s, stage):
                if s["current_stage"] + 1 >= len(cfg["approval_stages"]):
                    s2 = await guarded("srns", sid, ["IN_REVIEW"], {"status": "APPROVED", "approved_at": now()})
                    for it in s["items"]:
                        cr = await db.change_requests.find_one({"id": it["cr_id"]}, {"_id": 0})
                        if it["scope"] == "full" and cr["status"] == "RELEASE_APPROVAL_PENDING":
                            await set_cr_status(cr, "UAT_DEPLOYMENT_PENDING", u, f"SRN {s['number']} approved")
                    await notify([s["author_id"]] + await project_users(s["project_id"], {"pm", "team_lead"}), "SRN_APPROVED", f"SRN {s['number']} fully approved — deployment can be authorized", link)
                else:
                    s2 = await guarded("srns", sid, ["IN_REVIEW"], {"current_stage": s["current_stage"] + 1})
                    await notify(await _stage_approvers(s2, cfg), "SRN_APPROVAL_REQUESTED", f"SRN {s['number']} awaits your approval", link, dedupe=f"srn:{sid}:r{s['revision']}:s{s2['current_stage']}")
            else:
                s2 = await guarded("srns", sid, ["IN_REVIEW"], {})
        elif d == "HOLD":
            hold = {"reason": body.hold_reason, "responsible_id": body.responsible_id, "expected_date": body.expected_date, "notes": body.comment,
                    "by": u["id"], "by_name": u["name"], "role": role, "stage": stage_key, "at": now()}
            s2 = await guarded("srns", sid, ["IN_REVIEW"], {"status": "ON_HOLD", "hold": hold})
            bas = await project_users(s["project_id"], {"ba", "ba_lead"})
            await notify([body.responsible_id, s["author_id"]] + bas, "SRN_ON_HOLD", f"SRN {s['number']} put on hold", link, body.hold_reason)
        else:
            to = "REJECTED" if d == "REJECT" else "CHANGES_REQUESTED"
            s2 = await guarded("srns", sid, ["IN_REVIEW"], {"status": to, "current_stage": 0})
            await db.srn_approvals.update_many({"srn_id": sid, "valid": True}, {"$set": {"valid": False, "invalidated_at": now(), "invalidated_reason": d}})
            if d == "REJECT":
                await _release_scope(s, u, back=True)
            await notify([s["author_id"]], "SRN_REJECTED" if d == "REJECT" else "SRN_CHANGES", f"SRN {s['number']} {to.replace('_', ' ').lower()}", link, body.comment)
    if d != "APPROVE":
        await db.srn_approvals.insert_one({"id": uid(), "srn_id": sid, "stage": stage_key, "revision": s["revision"], "approver_id": u["id"], "approver_name": u["name"],
                                           "role": role, "role_label": ROLES.get(role, {}).get("label", ""), "decision": d,
                                           "comment": body.comment or body.hold_reason, "before": before, "after": s2["status"], "valid": False, "at": now()})
    await audit(u, f"SRN_{d}", "srn", sid, s["project_id"], {"status": before}, {"status": s2["status"], "stage": s2["current_stage"]}, body.comment or body.hold_reason)
    return s2


@router.get("/srns")
async def list_srns(u=Depends(current_user), project_id: str = "", status: str = ""):
    f = pscope(await my_project_ids(u))
    if project_id:
        f["project_id"] = project_id
    if status:
        f["status"] = {"$in": status.split(",")}
    items = await db.srns.find(f, {"_id": 0}).sort("created_at", -1).to_list(500)
    projs = {p["id"]: p["name"] for p in await db.projects.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(500)}
    for s in items:
        s["project_name"] = projs.get(s["project_id"])
    return items


@router.get("/srns/{sid}")
async def get_srn(sid: str, u=Depends(current_user)):
    s = await load_srn(u, sid)
    cfg = await _config(s["project_id"])
    s["approvals"] = await db.srn_approvals.find({"srn_id": sid}, {"_id": 0}).sort("at", 1).to_list(200)
    s["stages"] = []
    for i, st in enumerate(cfg["approval_stages"]):
        s["stages"].append({**st, "index": i, "required_roles": await _required_roles(s["project_id"], st),
                            "complete": (await _stage_complete(s, st)) if s["status"] != "DRAFT" else False})
    ok, reason, _ = await can_approve(u, s, cfg)
    s["can_approve"], s["approve_block_reason"] = ok, reason
    s["deployments"] = await db.deployments.find({"srn_id": sid}, {"_id": 0}).sort("created_at", -1).to_list(50)
    s["emails"] = await db.email_messages.find({"srn_id": sid}, {"_id": 0, "html": 0}).sort("created_at", -1).to_list(50)
    s["revisions"] = await db.srn_revisions.find({"srn_id": sid}, {"_id": 0}).sort("revision", -1).to_list(50)
    s["artifacts"] = await db.srn_artifacts.find({"srn_id": sid}, {"_id": 0}).sort("at", -1).to_list(50)
    s["activity"] = await db.audit_logs.find({"entity_id": sid}, {"_id": 0}).sort("at", -1).to_list(200)
    pr = await db.project_members.find_one({"project_id": s["project_id"], "user_id": u["id"]}, {"_id": 0})
    s["my_project_role"] = "system_admin" if is_admin(u) else (pr or {}).get("project_role")
    s["project_name"] = (await db.projects.find_one({"id": s["project_id"]}, {"_id": 0, "name": 1}))["name"]
    return s


async def _ctx(s):
    proj = await db.projects.find_one({"id": s["project_id"]}, {"_id": 0})
    approvals = await db.srn_approvals.find({"srn_id": s["id"]}, {"_id": 0}).sort("at", 1).to_list(200)
    history = await db.srns.find({"project_id": s["project_id"], "application_name": s.get("application_name"), "created_at": {"$lte": s["created_at"]},
                                  "status": {"$nin": ["REJECTED"]}}, {"_id": 0, "release_version": 1, "release_date": 1, "author_name": 1}).sort("created_at", 1).to_list(100)
    return srn_context(s, proj, approvals, history), proj


@router.get("/srns/{sid}/document")
async def srn_document(sid: str, format: str = "pdf", u=Depends(current_user)):
    s = await load_srn(u, sid)
    ctx, _ = await _ctx(s)
    data = build_pdf(ctx) if format == "pdf" else build_docx(ctx)
    await db.srn_artifacts.insert_one({"id": uid(), "srn_id": sid, "format": format, "revision": s["revision"], "template_version": "SRN-T1", "by": u["name"], "at": now()})
    mt = "application/pdf" if format == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return Response(content=data, media_type=mt, headers={"Content-Disposition": f'attachment; filename="{s["number"]}_{s.get("release_version", "")}.{format}"'})


@router.get("/srns/{sid}/preview")
async def srn_preview(sid: str, u=Depends(current_user)):
    s = await load_srn(u, sid)
    ctx, _ = await _ctx(s)
    return ctx


@router.get("/approvals/queue")
async def approval_queue(u=Depends(current_user)):
    f = pscope(await my_project_ids(u))
    out = []
    for s in await db.srns.find({**f, "status": {"$in": ["IN_REVIEW", "ON_HOLD"]}}, {"_id": 0}).sort("submitted_at", 1).to_list(300):
        ok, reason, _ = await can_approve(u, s)
        hold = s.get("hold") or {}
        if ok or (s["status"] == "ON_HOLD" and u["id"] in (hold.get("by"), hold.get("responsible_id"))):
            cfg = await _config(s["project_id"])
            s["stage_label"] = cfg["approval_stages"][s["current_stage"]]["label"]
            out.append(s)
    return out


async def _deploy_permitted(u, s):
    pr = await require_project(u, s["project_id"])
    if not (is_admin(u) or pr in ("pm", "team_lead", "senior_pm", "project_lead")):
        err(403, "Only PM / Team Lead can authorize or confirm deployments")


@router.post("/srns/{sid}/deployments")
async def authorize_deployment(sid: str, body: DeployIn, u=Depends(current_user)):
    s = await load_srn(u, sid)
    await _deploy_permitted(u, s)
    if s["status"] not in ("APPROVED", "DEPLOYMENT_FAILED"):
        err(409, "Deployment requires a fully approved SRN")
    d = {"id": uid(), "srn_id": sid, "srn_number": s["number"], "project_id": s["project_id"], "environment": body.environment or s.get("environment", "UAT"),
         "version": s["release_version"], "status": "DEPLOYMENT_PENDING", "authorized_by": u["id"], "authorized_by_name": u["name"],
         "build_id": body.build_id or s.get("build_ref", ""), "notes": body.notes, "created_at": now()}
    await db.deployments.insert_one(dict(d))
    await guarded("srns", sid, [s["status"]], {"status": "DEPLOYMENT_PENDING"})
    await audit(u, "DEPLOYMENT_AUTHORIZED", "srn", sid, s["project_id"], {"status": s["status"]}, {"status": "DEPLOYMENT_PENDING"})
    d.pop("_id", None)
    return d


@router.post("/deployments/{did}/start")
async def start_deployment(did: str, u=Depends(current_user)):
    d = await db.deployments.find_one({"id": did}, {"_id": 0})
    if not d:
        err(404, "Not found")
    s = await load_srn(u, d["srn_id"])
    await _deploy_permitted(u, s)
    d = await guarded("deployments", did, ["DEPLOYMENT_PENDING"], {"status": "DEPLOYMENT_IN_PROGRESS", "started_at": now(), "deployed_by": u["id"], "deployed_by_name": u["name"]})
    await guarded("srns", s["id"], ["DEPLOYMENT_PENDING"], {"status": "DEPLOYMENT_IN_PROGRESS"})
    await audit(u, "DEPLOYMENT_STARTED", "srn", s["id"], s["project_id"])
    return d


@router.post("/deployments/{did}/confirm")
async def confirm_deployment(did: str, body: DeployIn, u=Depends(current_user)):
    d = await db.deployments.find_one({"id": did}, {"_id": 0})
    if not d:
        err(404, "Not found")
    s = await load_srn(u, d["srn_id"])
    await _deploy_permitted(u, s)
    if body.success is None:
        err(400, "Specify success or failure")
    if not body.success:
        if not body.failure_details:
            err(400, "Failure details are required")
        d = await guarded("deployments", did, ["DEPLOYMENT_IN_PROGRESS"], {"status": "DEPLOYMENT_FAILED", "completed_at": now(), "failure_details": body.failure_details, "rollback_result": body.rollback_result, "notes": body.notes})
        await guarded("srns", s["id"], ["DEPLOYMENT_IN_PROGRESS"], {"status": "DEPLOYMENT_FAILED"})
        await audit(u, "DEPLOYMENT_FAILED", "srn", s["id"], s["project_id"], None, {"failure": body.failure_details})
        await notify([s["author_id"]], "DEPLOYMENT_FAILED", f"Deployment failed for {s['number']}", f"/srns/{s['id']}", body.failure_details)
        return d
    d = await guarded("deployments", did, ["DEPLOYMENT_IN_PROGRESS"], {"status": "UAT_DEPLOYED", "completed_at": now(), "build_id": body.build_id or d.get("build_id"), "notes": body.notes})
    s = await guarded("srns", s["id"], ["DEPLOYMENT_IN_PROGRESS"], {"status": "UAT_DEPLOYED", "deployed_at": now()})
    await _after_deploy(s, d, u)
    return d


async def _after_deploy(s, d, u):
    uat_ids = await project_users(s["project_id"], {"uat_lead", "uat_manager", "uat_member"})
    tids = [t for i in s["items"] for t in i["task_ids"]]
    await db.cr_tasks.update_many({"id": {"$in": tids}}, {"$set": {"status": "READY_FOR_UAT", "released_at": now()}})
    for it in s["items"]:
        cr = await db.change_requests.find_one({"id": it["cr_id"]}, {"_id": 0})
        if it["scope"] == "full" and cr["status"] == "UAT_DEPLOYMENT_PENDING":
            await set_cr_status(cr, "UAT_DEPLOYED", u, f"Deployed via {s['number']}")
        await db.uat_assignments.insert_one({"id": uid(), "project_id": s["project_id"], "srn_id": s["id"], "srn_number": s["number"], "deployment_id": d["id"],
                                             "cr_id": it["cr_id"], "cr_number": it["cr_number"], "title": it["title"], "scope": it["scope"], "kind": "CR",
                                             "task_ids": it["task_ids"], "status": "PENDING", "assignee_ids": uat_ids, "test_cases": [], "retest_bug_ids": [],
                                             "created_at": now(), "updated_at": now()})
    for b in s.get("bug_items", []):
        await db.bugs.update_one({"id": b["id"]}, {"$set": {"status": "UAT_DEPLOYED", "deployment_id": d["id"], "fix_srn_id": s["id"]}})
        ua = await db.uat_assignments.find_one({"cr_id": b.get("cr_id"), "status": {"$in": ["FAILED", "ON_HOLD", "IN_PROGRESS", "RETEST_PENDING"]}}, {"_id": 0}, sort=[("created_at", -1)])
        if ua:
            await db.uat_assignments.update_one({"id": ua["id"]}, {"$set": {"status": "RETEST_PENDING", "updated_at": now()}, "$addToSet": {"retest_bug_ids": b["id"]}})
        else:
            cr = await db.change_requests.find_one({"id": b.get("cr_id")}, {"_id": 0}) or {}
            await db.uat_assignments.insert_one({"id": uid(), "project_id": s["project_id"], "srn_id": s["id"], "srn_number": s["number"], "deployment_id": d["id"],
                                                 "cr_id": b.get("cr_id"), "cr_number": cr.get("number"), "title": f"Retest {b['number']}", "scope": "bugfix", "kind": "BUG_RETEST",
                                                 "task_ids": [], "status": "RETEST_PENDING", "assignee_ids": uat_ids, "test_cases": [], "retest_bug_ids": [b["id"]],
                                                 "created_at": now(), "updated_at": now()})
        cr = await db.change_requests.find_one({"id": b.get("cr_id")}, {"_id": 0})
        if cr and cr["status"] in ("UAT_FAILED", "UAT_HOLD"):
            await set_cr_status(cr, "UAT_DEPLOYED", u, f"Bug fix {b['number']} deployed via {s['number']}")
    await audit(u, "DEPLOYMENT_CONFIRMED", "srn", s["id"], s["project_id"], None, {"deployment_id": d["id"], "environment": d["environment"]})
    await notify(uat_ids + await project_users(s["project_id"], {"ba"}), "UAT_DEPLOYED", f"{s['number']} deployed to {d['environment']} — ready for UAT", "/uat")
    cfg = await _config(s["project_id"])
    proj = await db.projects.find_one({"id": s["project_id"]}, {"_id": 0})

    async def emails(roles):
        ids = await project_users(s["project_id"], set(roles))
        us = await db.users.find({"id": {"$in": ids}, "active": True, "notify_email": {"$ne": False}}, {"_id": 0, "email": 1}).to_list(500)
        return [x["email"] for x in us]
    to = await emails(cfg["email_to_roles"]) + cfg.get("email_extra_to", [])
    cc = await emails(cfg["email_cc_roles"]) + cfg.get("email_extra_cc", [])
    anchor = (s["items"][0]["cr_id"] if s["items"] else (s["bug_items"][0].get("cr_id") if s.get("bug_items") else s["id"]))
    follow = bool(s.get("bug_items")) and not s["items"]
    subject = f"[CReMS] {proj['name']} — SRN {s['number']} {s['release_version']} deployed to {d['environment']}"
    html = srn_email_html(s, proj, s["items"], s.get("bug_items", []), d, follow)
    await queue_email(f"srn:{s['id']}:deploy:{d['id']}", "SRN_RELEASE", s["project_id"], to, cc, subject, html, srn_id=s["id"], thread_key=f"proj:{s['project_id']}:cr:{anchor}")


@router.get("/emails")
async def list_emails(u=Depends(current_user)):
    f = pscope(await my_project_ids(u))
    return await db.email_messages.find(f, {"_id": 0, "html": 0}).sort("created_at", -1).to_list(300)


@router.post("/emails/{mid}/retry")
async def retry_email(mid: str, u=Depends(current_user)):
    m = await db.email_messages.find_one({"id": mid}, {"_id": 0})
    if not m:
        err(404, "Not found")
    pr = await require_project(u, m["project_id"])
    if not (is_admin(u) or pr in ("pm", "team_lead")):
        err(403, "Not allowed")
    if m["status"] != "FAILED":
        err(409, "Only failed emails can be retried")
    await db.email_messages.update_one({"id": mid}, {"$set": {"status": "QUEUED", "attempts": 0, "next_attempt_at": now()}})
    await audit(u, "EMAIL_RETRY", "email", mid, m["project_id"])
    return {"ok": True}
