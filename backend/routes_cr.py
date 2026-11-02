import re
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from core import (db, now, uid, err, audit, notify, guarded, current_user, my_project_ids, pscope, require_project,
                  member_role, next_number, project_users, users_map, MANAGERS, DEV_EXEC, BA_ROLES, UAT_ROLES)
from workflow import set_cr_status, recompute_cr, cr_ba_ids, is_ba, is_mgr, BUG_CLOSED

router = APIRouter(prefix="/api")
BUSINESS_FIELDS = ["title", "description", "business_requirements", "expected_result", "justification", "priority",
                   "requested_deadline", "business_owner", "acceptance_criteria", "impacted_module_ids",
                   "impacted_screen_ids", "attachments"]


class CRIn(BaseModel):
    title: str
    project_id: str
    description: str = ""
    business_requirements: str = ""
    expected_result: str = ""
    justification: str = ""
    priority: str = "Medium"
    requested_deadline: Optional[str] = None
    business_owner: str = ""
    ba_id: Optional[str] = None
    acceptance_criteria: str = ""
    impacted_module_ids: List[str] = []
    impacted_screen_ids: List[str] = []
    attachments: List[dict] = []
    submit: bool = True


class CRPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    business_requirements: Optional[str] = None
    expected_result: Optional[str] = None
    justification: Optional[str] = None
    priority: Optional[str] = None
    requested_deadline: Optional[str] = None
    business_owner: Optional[str] = None
    acceptance_criteria: Optional[str] = None
    impacted_module_ids: Optional[List[str]] = None
    impacted_screen_ids: Optional[List[str]] = None
    attachments: Optional[List[dict]] = None


class ActionIn(BaseModel):
    comment: Optional[str] = None
    manager_id: Optional[str] = None
    priority: Optional[str] = None
    requested_deadline: Optional[str] = None
    impact: Optional[dict] = None


class DeadlineIn(BaseModel):
    proposed_deadline: str
    reason: str
    dev_hours: float = 0
    sit_hours: float = 0
    dependencies: str = ""
    comments: str = ""
    module_ids: List[str] = []


class DecideIn(BaseModel):
    decision: str
    comment: Optional[str] = None


class TaskIn(BaseModel):
    title: str
    description: str = ""
    developer_id: str
    collaborator_ids: List[str] = []
    module_id: Optional[str] = None
    screen_id: Optional[str] = None
    priority: str = "Medium"
    planned_start: Optional[str] = None
    planned_end: Optional[str] = None
    estimated_hours: float = 0
    mandatory: bool = True


class TaskAction(BaseModel):
    result: Optional[str] = None
    evidence: Optional[str] = None
    notes: Optional[str] = None
    reason: Optional[str] = None
    git_ref: Optional[str] = None
    actual_hours: Optional[float] = None


class CommentIn(BaseModel):
    text: str


async def load_cr(u, cr_id):
    cr = await db.change_requests.find_one({"id": cr_id}, {"_id": 0})
    if not cr:
        err(404, "CR not found")
    pr = await require_project(u, cr["project_id"])
    return cr, pr


@router.get("/crs")
async def list_crs(u=Depends(current_user), q: str = "", project_id: str = "", status: str = "", priority: str = "",
                   source: str = "", ba_id: str = "", manager_id: str = "", developer_id: str = "", module_id: str = "",
                   date_from: str = "", date_to: str = "",
                   page: int = Query(1, ge=1), page_size: int = Query(25, le=500), sort: str = "-updated_at"):
    f = pscope(await my_project_ids(u))
    if project_id:
        f = {"$and": [f, {"project_id": project_id}]} if f else {"project_id": project_id}
    for k, v in [("status", status), ("priority", priority), ("source", source), ("ba_id", ba_id), ("manager_id", manager_id)]:
        if v:
            f[k] = {"$in": v.split(",")}
    if module_id:
        f["impacted_module_ids"] = module_id
    if developer_id:
        f["id"] = {"$in": await db.cr_tasks.distinct("cr_id", {"developer_id": developer_id})}
    if date_from or date_to:
        f["created_at"] = {k: v for k, v in [("$gte", date_from), ("$lte", date_to + "T23:59:59" if date_to else "")] if v}
    if q:
        f["$or"] = [{"title": {"$regex": re.escape(q), "$options": "i"}}, {"number": {"$regex": re.escape(q), "$options": "i"}}]
    total = await db.change_requests.count_documents(f)
    direction = -1 if sort.startswith("-") else 1
    items = await db.change_requests.find(f, {"_id": 0, "status_history": 0}).sort(sort.lstrip("-"), direction) \
        .skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    await enrich(items)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def enrich(items):
    um = await users_map([x.get("ba_id") for x in items] + [x.get("manager_id") for x in items])
    projs = {p["id"]: p["name"] for p in await db.projects.find({"id": {"$in": list({x["project_id"] for x in items})}}, {"_id": 0, "id": 1, "name": 1}).to_list(500)}
    for x in items:
        x["project_name"] = projs.get(x["project_id"])
        x["ba_name"] = um.get(x.get("ba_id"), {}).get("name")
        x["manager_name"] = um.get(x.get("manager_id"), {}).get("name")
        ts = await db.cr_tasks.find({"cr_id": x["id"], "status": {"$ne": "CANCELLED"}}, {"_id": 0, "status": 1}).to_list(200)
        x["task_total"] = len(ts)
        x["task_done"] = sum(1 for t in ts if t["status"] in ("SIT_PASSED", "READY_FOR_UAT"))
        ua = await db.uat_assignments.find_one({"cr_id": x["id"]}, {"_id": 0, "status": 1}, sort=[("created_at", -1)])
        x["uat_status"] = ua["status"] if ua else None


@router.post("/crs")
async def create_cr(body: CRIn, u=Depends(current_user)):
    pr = await require_project(u, body.project_id)
    if not is_ba(u, pr):
        err(403, "Only Business Analysts can create CRs")
    ba_id = body.ba_id or (u["id"] if u["role"] in BA_ROLES else None)
    if ba_id and not (await db.project_members.find_one({"project_id": body.project_id, "user_id": ba_id, "project_role": {"$in": list(BA_ROLES)}})):
        err(400, "Assigned BA must be a BA member of this project")
    doc = {**body.model_dump(exclude={"submit"}), "id": uid(), "number": await next_number("CR"), "source": "INTERNAL",
           "external_id": None, "ba_id": ba_id, "manager_id": None, "approved_deadline": None, "impact": {},
           "status": "NEW" if body.submit else "DRAFT", "revision": 1, "created_by": u["id"], "created_by_name": u["name"],
           "created_at": now(), "updated_at": now(), "version": 1, "comments": [],
           "status_history": [{"from": None, "to": "NEW" if body.submit else "DRAFT", "by": u["id"], "by_name": u["name"], "at": now()}]}
    await db.change_requests.insert_one(dict(doc))
    await db.cr_revisions.insert_one({"id": uid(), "cr_id": doc["id"], "revision": 1, "snapshot": {k: doc[k] for k in BUSINESS_FIELDS}, "by": u["id"], "at": now()})
    await audit(u, "CR_CREATED", "cr", doc["id"], body.project_id, None, {"number": doc["number"], "status": doc["status"]})
    if body.submit:
        await notify([ba_id], "CR_BA_VALIDATION", f"{doc['number']} requires BA validation", f"/crs/{doc['id']}")
    doc.pop("_id", None)
    return doc


@router.get("/crs/{cr_id}")
async def get_cr(cr_id: str, u=Depends(current_user)):
    cr, pr = await load_cr(u, cr_id)
    await enrich([cr])
    cr["my_project_role"] = pr
    cr["tasks"] = await db.cr_tasks.find({"cr_id": cr_id}, {"_id": 0}).sort("created_at", 1).to_list(500)
    um = await users_map([t["developer_id"] for t in cr["tasks"]] + [c for t in cr["tasks"] for c in t.get("collaborator_ids", [])])
    for t in cr["tasks"]:
        t["developer_name"] = um.get(t["developer_id"], {}).get("name")
        t["sit_results"] = await db.task_sit_results.find({"task_id": t["id"]}, {"_id": 0}).sort("at", -1).to_list(50)
    cr["bugs"] = await db.bugs.find({"cr_id": cr_id}, {"_id": 0}).sort("created_at", -1).to_list(500)
    cr["srns"] = await db.srns.find({"items.cr_id": cr_id}, {"_id": 0, "id": 1, "number": 1, "version": 1, "release_version": 1, "status": 1, "created_at": 1}).to_list(100)
    cr["deadline_requests"] = await db.deadline_requests.find({"cr_id": cr_id}, {"_id": 0}).sort("created_at", -1).to_list(100)
    cr["approvals"] = await db.srn_approvals.find({"srn_id": {"$in": [s["id"] for s in cr["srns"]]}}, {"_id": 0}).sort("at", -1).to_list(200)
    cr["assignments"] = await db.cr_assignments.find({"cr_id": cr_id}, {"_id": 0}).sort("at", -1).to_list(100)
    cr["uat"] = await db.uat_assignments.find({"cr_id": cr_id}, {"_id": 0}).sort("created_at", -1).to_list(50)
    cr["revisions"] = await db.cr_revisions.find({"cr_id": cr_id}, {"_id": 0}).sort("revision", -1).to_list(50)
    cr["activity"] = await db.audit_logs.find({"$or": [{"entity_id": cr_id}, {"meta.cr_id": cr_id}]}, {"_id": 0}).sort("at", -1).to_list(300)
    mods = await db.modules.find({"id": {"$in": cr.get("impacted_module_ids", [])}}, {"_id": 0, "id": 1, "name": 1}).to_list(100)
    scr = await db.screens.find({"id": {"$in": cr.get("impacted_screen_ids", [])}}, {"_id": 0, "id": 1, "name": 1}).to_list(200)
    cr["impacted_modules"], cr["impacted_screens"] = mods, scr
    return cr


@router.patch("/crs/{cr_id}")
async def patch_cr(cr_id: str, body: CRPatch, u=Depends(current_user)):
    cr, pr = await load_cr(u, cr_id)
    if not is_ba(u, pr):
        err(403, "Only the BA can edit business fields")
    if cr["status"] in ("CLOSED", "CANCELLED"):
        err(409, "Closed CRs cannot be edited")
    changes = {k: v for k, v in body.model_dump(exclude_none=True).items() if cr.get(k) != v}
    if not changes:
        return cr
    extra = {}
    if cr["status"] not in ("DRAFT", "NEW", "BA_REVIEW"):
        extra["needs_impact_review"] = True
    rev = cr.get("revision", 1) + 1
    doc = await guarded("change_requests", cr_id, None, {**changes, **extra, "revision": rev})
    await db.cr_revisions.insert_one({"id": uid(), "cr_id": cr_id, "revision": rev, "snapshot": {k: doc.get(k) for k in BUSINESS_FIELDS}, "changed": list(changes), "by": u["id"], "at": now()})
    await audit(u, "CR_UPDATED", "cr", cr_id, cr["project_id"], {k: cr.get(k) for k in changes}, changes)
    if extra:
        await notify([cr.get("manager_id")], "CR_IMPACT_REVIEW", f"{cr['number']} requirements changed — impact review needed", f"/crs/{cr_id}")
    return doc


@router.post("/crs/{cr_id}/comments")
async def add_comment(cr_id: str, body: CommentIn, u=Depends(current_user)):
    cr, _ = await load_cr(u, cr_id)
    c = {"id": uid(), "text": body.text, "by": u["id"], "by_name": u["name"], "at": now()}
    await db.change_requests.update_one({"id": cr_id}, {"$push": {"comments": c}})
    await audit(u, "CR_COMMENT", "cr", cr_id, cr["project_id"], comment=body.text)
    return c


async def _check_manager(project_id, manager_id):
    m = await db.project_members.find_one({"project_id": project_id, "user_id": manager_id, "project_role": {"$in": ["senior_pm", "pm", "team_lead", "project_lead"]}})
    if not m:
        err(400, "Selected manager is not a development manager on this project")


@router.post("/crs/{cr_id}/actions/{action}")
async def cr_action(cr_id: str, action: str, body: ActionIn, u=Depends(current_user)):
    cr, pr = await load_cr(u, cr_id)
    st = cr["status"]
    link = f"/crs/{cr_id}"
    if action == "submit":
        if not is_ba(u, pr):
            err(403, "Only BA can submit")
        cr = await set_cr_status(cr, "NEW", u) if st == "DRAFT" else err(409, "Only drafts can be submitted")
        await notify([cr.get("ba_id")], "CR_BA_VALIDATION", f"{cr['number']} requires BA validation", link)
    elif action in ("start_review", "request_clarification", "reject", "ba_approve"):
        if not is_ba(u, pr):
            err(403, "Only the Business Analyst can perform BA review actions")
        if st not in ("NEW", "BA_REVIEW"):
            err(409, f"CR is in {st}; BA review actions are not allowed")
        if action == "start_review":
            cr = await set_cr_status(cr, "BA_REVIEW", u, body.comment)
        elif action == "request_clarification":
            if not body.comment:
                err(400, "Clarification comment is required")
            cr = await set_cr_status(cr, "BA_REVIEW", u, body.comment, {"clarification_requested": True})
            await notify([cr.get("created_by")], "CR_CLARIFICATION", f"Clarification requested on {cr['number']}", link, body.comment)
        elif action == "reject":
            if not body.comment:
                err(400, "Rejection reason is required")
            cr = await set_cr_status(cr, "CANCELLED", u, body.comment, {"rejected": True})
        else:
            if not body.manager_id:
                err(400, "Select the Senior PM / PM to assign")
            await _check_manager(cr["project_id"], body.manager_id)
            extra = {"manager_id": body.manager_id, "clarification_requested": False}
            if body.priority:
                extra["priority"] = body.priority
            if body.requested_deadline:
                extra["requested_deadline"] = body.requested_deadline
            if not (extra.get("requested_deadline") or cr.get("requested_deadline")):
                err(400, "Requested deadline is required before approval")
            cr = await set_cr_status(cr, "IMPACT_ANALYSIS", u, body.comment, extra)
            await db.cr_assignments.insert_one({"id": uid(), "cr_id": cr_id, "from_id": u["id"], "from_name": u["name"], "to_id": body.manager_id, "kind": "MANAGER", "at": now()})
            await notify([body.manager_id], "CR_ASSIGNED", f"{cr['number']} assigned to you for impact analysis", link)
    elif action == "reassign":
        if not body.manager_id or not (is_ba(u, pr) or is_mgr(u, pr)):
            err(403, "Not allowed")
        await _check_manager(cr["project_id"], body.manager_id)
        cr = await guarded("change_requests", cr_id, None, {"manager_id": body.manager_id})
        await db.cr_assignments.insert_one({"id": uid(), "cr_id": cr_id, "from_id": u["id"], "from_name": u["name"], "to_id": body.manager_id, "kind": "MANAGER", "at": now(), "comment": body.comment})
        await audit(u, "CR_REASSIGNED", "cr", cr_id, cr["project_id"], None, {"manager_id": body.manager_id}, body.comment)
        await notify([body.manager_id], "CR_ASSIGNED", f"{cr['number']} assigned to you", link)
    elif action == "save_impact":
        if not is_mgr(u, pr):
            err(403, "Only development managers can record impact analysis")
        if st not in ("IMPACT_ANALYSIS", "DEADLINE_APPROVAL_PENDING", "ASSIGNED", "IN_DEVELOPMENT"):
            err(409, "Impact analysis is not editable in this status")
        imp = body.impact or {}
        sets = {"impact": {**cr.get("impact", {}), **imp, "by": u["id"], "at": now()}, "needs_impact_review": False}
        if imp.get("module_ids") is not None:
            sets["impacted_module_ids"] = imp["module_ids"]
        if imp.get("screen_ids") is not None:
            sets["impacted_screen_ids"] = imp["screen_ids"]
        cr = await guarded("change_requests", cr_id, None, sets)
        await audit(u, "CR_IMPACT_SAVED", "cr", cr_id, cr["project_id"], None, imp)
    elif action == "confirm_assignment":
        if not is_mgr(u, pr):
            err(403, "Only development managers can confirm assignments")
        if st != "IMPACT_ANALYSIS":
            err(409, "Assignments can be confirmed only during impact analysis")
        if not await db.cr_tasks.count_documents({"cr_id": cr_id, "status": {"$ne": "CANCELLED"}}):
            err(400, "Create at least one development task first")
        extra = {} if cr.get("approved_deadline") else {"approved_deadline": cr.get("requested_deadline")}
        cr = await set_cr_status(cr, "ASSIGNED", u, body.comment, extra)
        cr = await recompute_cr(cr_id, u)
        await notify(await cr_ba_ids(cr), "CR_ASSIGNED", f"{cr['number']} development assigned", link)
    elif action == "notify_uat":
        if not is_ba(u, pr):
            err(403, "Only BA can nominate UAT")
        ids = await project_users(cr["project_id"], {"uat_lead", "uat_manager"})
        await notify(ids, "UAT_HEADS_UP", f"Upcoming UAT: {cr['number']} {cr['title']}", link, body.comment or "BA nominated UAT team early (not deployed yet).")
        await audit(u, "UAT_NOMINATED", "cr", cr_id, cr["project_id"], comment=body.comment)
    elif action == "close":
        if not is_ba(u, pr):
            err(403, "Only BA can grant final business acceptance")
        if st != "UAT_PASSED":
            err(409, "Only UAT-passed CRs can be closed")
        if await db.bugs.count_documents({"cr_id": cr_id, "status": {"$nin": list(BUG_CLOSED)}}):
            err(409, "Open bugs remain on this CR")
        if await db.cr_tasks.count_documents({"cr_id": cr_id, "status": {"$nin": ["READY_FOR_UAT", "CANCELLED"]}}):
            err(409, "Some required scope has not been released and accepted yet")
        cr = await set_cr_status(cr, "CLOSED", u, body.comment, {"closed_at": now()})
    elif action == "cancel":
        if not (u["role"] in ("system_admin", "ba_lead") or pr == "ba_lead"):
            err(403, "Only BA Lead or Admin can cancel")
        if st in ("CLOSED", "CANCELLED"):
            err(409, "Already finished")
        if not body.comment:
            err(400, "Reason required")
        cr = await set_cr_status(cr, "CANCELLED", u, body.comment)
    else:
        err(400, "Unknown action")
    return cr


@router.post("/crs/{cr_id}/deadline-requests")
async def create_deadline(cr_id: str, body: DeadlineIn, u=Depends(current_user)):
    cr, pr = await load_cr(u, cr_id)
    if not is_mgr(u, pr):
        err(403, "Only development managers can request deadline revisions")
    if cr["status"] in ("CLOSED", "CANCELLED", "DRAFT", "NEW", "BA_REVIEW"):
        err(409, "Deadline revision not allowed in this status")
    if await db.deadline_requests.find_one({"cr_id": cr_id, "status": "PENDING"}):
        err(409, "A deadline request is already pending")
    d = {**body.model_dump(), "id": uid(), "cr_id": cr_id, "project_id": cr["project_id"], "cr_number": cr["number"],
         "original_deadline": cr.get("requested_deadline"), "current_approved": cr.get("approved_deadline"),
         "status": "PENDING", "requested_by": u["id"], "requested_by_name": u["name"], "created_at": now(),
         "prev_cr_status": cr["status"]}
    await db.deadline_requests.insert_one(dict(d))
    if cr["status"] == "IMPACT_ANALYSIS":
        await set_cr_status(cr, "DEADLINE_APPROVAL_PENDING", u, body.reason)
    await audit(u, "DEADLINE_REQUESTED", "cr", cr_id, cr["project_id"], None, {"proposed": body.proposed_deadline}, body.reason)
    await notify(await cr_ba_ids(cr), "DEADLINE_REVISION", f"Deadline revision requested on {cr['number']}", f"/crs/{cr_id}", body.reason)
    d.pop("_id", None)
    return d


@router.post("/deadline-requests/{rid}/decide")
async def decide_deadline(rid: str, body: DecideIn, u=Depends(current_user)):
    d = await db.deadline_requests.find_one({"id": rid}, {"_id": 0})
    if not d:
        err(404, "Not found")
    cr, pr = await load_cr(u, d["cr_id"])
    if not is_ba(u, pr):
        err(403, "Only the BA can decide deadline requests")
    if body.decision not in ("APPROVE", "REJECT", "REVISE"):
        err(400, "Invalid decision")
    if body.decision != "APPROVE" and not body.comment:
        err(400, "Comment required")
    new = {"APPROVE": "APPROVED", "REJECT": "REJECTED", "REVISE": "REVISION_REQUESTED"}[body.decision]
    d = await guarded("deadline_requests", rid, ["PENDING"], {"status": new, "decided_by": u["id"], "decided_by_name": u["name"], "decided_at": now(), "decision_comment": body.comment})
    extra = {"approved_deadline": d["proposed_deadline"]} if new == "APPROVED" else {}
    back = d["prev_cr_status"] if cr["status"] == "DEADLINE_APPROVAL_PENDING" else cr["status"]
    await set_cr_status(cr, back, u, f"Deadline request {new.lower()}", extra)
    await audit(u, "DEADLINE_" + new, "cr", cr["id"], cr["project_id"], {"approved_deadline": cr.get("approved_deadline")}, extra or None, body.comment)
    await notify([d["requested_by"]], "DEADLINE_DECISION", f"Deadline request {new.replace('_', ' ').lower()} for {cr['number']}", f"/crs/{cr['id']}", body.comment or "")
    return d


@router.get("/deadline-requests")
async def list_deadlines(u=Depends(current_user), status: str = "PENDING"):
    f = pscope(await my_project_ids(u))
    if status:
        f["status"] = status
    return await db.deadline_requests.find(f, {"_id": 0}).sort("created_at", -1).to_list(200)


@router.post("/crs/{cr_id}/tasks")
async def create_task(cr_id: str, body: TaskIn, u=Depends(current_user)):
    cr, pr = await load_cr(u, cr_id)
    if not is_mgr(u, pr):
        err(403, "Only PM / Team Lead / Senior PM can assign tasks")
    if cr["status"] not in ("IMPACT_ANALYSIS", "ASSIGNED", "IN_DEVELOPMENT", "SIT_IN_PROGRESS", "READY_FOR_UAT", "UAT_FAILED"):
        err(409, f"Tasks cannot be added while CR is {cr['status']}")
    dev_role = await member_role({"id": body.developer_id}, cr["project_id"])
    if dev_role not in DEV_EXEC:
        err(400, "Developer must be a PM / Team Lead / Developer member of this project")
    for c in body.collaborator_ids:
        if not await member_role({"id": c}, cr["project_id"]):
            err(400, "Collaborators must be project members")
    num = await next_number("T")
    t = {**body.model_dump(), "id": uid(), "number": num, "cr_id": cr_id, "cr_number": cr["number"], "project_id": cr["project_id"],
         "status": "ASSIGNED", "assigned_by": u["id"], "assigned_by_name": u["name"], "self_assigned": body.developer_id == u["id"],
         "actual_hours": 0, "git_ref": "", "notes": "", "srn_id": None, "created_at": now(), "updated_at": now(), "version": 1}
    await db.cr_tasks.insert_one(dict(t))
    await db.cr_assignments.insert_one({"id": uid(), "cr_id": cr_id, "from_id": u["id"], "from_name": u["name"], "to_id": body.developer_id, "kind": "TASK", "task_id": t["id"], "at": now()})
    await audit(u, "TASK_ASSIGNED", "task", t["id"], cr["project_id"], None, {"developer_id": body.developer_id, "title": body.title}, meta={"cr_id": cr_id})
    await notify([body.developer_id] + body.collaborator_ids, "TASK_ASSIGNED", f"New task {num}: {body.title}", f"/crs/{cr_id}")
    await recompute_cr(cr_id, u)
    t.pop("_id", None)
    return t


@router.get("/tasks")
async def list_tasks(u=Depends(current_user), mine: bool = True, status: str = "", project_id: str = ""):
    f = pscope(await my_project_ids(u))
    if mine:
        f["$or"] = [{"developer_id": u["id"]}, {"collaborator_ids": u["id"]}]
    if status:
        f["status"] = {"$in": status.split(",")}
    if project_id:
        f["project_id"] = project_id
    items = await db.cr_tasks.find(f, {"_id": 0}).sort("updated_at", -1).to_list(500)
    um = await users_map([t["developer_id"] for t in items])
    for t in items:
        t["developer_name"] = um.get(t["developer_id"], {}).get("name")
    return items


TASK_FLOW = {
    "start": (["ASSIGNED", "SIT_FAILED"], "IN_DEVELOPMENT"),
    "complete_dev": (["IN_DEVELOPMENT"], "DEVELOPMENT_COMPLETED"),
    "start_sit": (["DEVELOPMENT_COMPLETED"], "SIT_IN_PROGRESS"),
}


@router.post("/tasks/{task_id}/actions/{action}")
async def task_action(task_id: str, action: str, body: TaskAction, u=Depends(current_user)):
    t = await db.cr_tasks.find_one({"id": task_id}, {"_id": 0})
    if not t:
        err(404, "Task not found")
    pr = await require_project(u, t["project_id"])
    owner = u["id"] == t["developer_id"] or u["id"] in t.get("collaborator_ids", [])
    sets = {}
    if body.git_ref is not None:
        sets["git_ref"] = body.git_ref
    if body.actual_hours is not None:
        sets["actual_hours"] = body.actual_hours
    if body.notes:
        sets["notes"] = body.notes
    if action in TASK_FLOW or action == "sit_result":
        if not owner:
            err(403, "Only the task developer can perform this action")
        if action == "sit_result":
            if body.result not in ("PASS", "FAIL"):
                err(400, "SIT result must be PASS or FAIL")
            if not body.evidence:
                err(400, "SIT evidence is required")
            to = "SIT_PASSED" if body.result == "PASS" else "SIT_FAILED"
            t2 = await guarded("cr_tasks", task_id, ["SIT_IN_PROGRESS"], {**sets, "status": to, "sit_result": body.result})
            await db.task_sit_results.insert_one({"id": uid(), "task_id": task_id, "result": body.result, "evidence": body.evidence, "notes": body.notes, "by": u["id"], "by_name": u["name"], "at": now()})
            cr = await db.change_requests.find_one({"id": t["cr_id"]}, {"_id": 0})
            await notify([t["assigned_by"], cr.get("manager_id")], "SIT_COMPLETED", f"SIT {body.result} on {t['number']}", f"/crs/{t['cr_id']}")
        else:
            frm, to = TASK_FLOW[action]
            t2 = await guarded("cr_tasks", task_id, frm, {**sets, "status": to})
    elif action == "block":
        if not (owner or is_mgr(u, pr)):
            err(403, "Not allowed")
        if not body.reason:
            err(400, "Blocking reason required")
        to = "BLOCKED"
        t2 = await guarded("cr_tasks", task_id, ["ASSIGNED", "IN_DEVELOPMENT", "DEVELOPMENT_COMPLETED", "SIT_IN_PROGRESS", "SIT_FAILED"], {"status": to, "prev_status": t["status"], "block_reason": body.reason})
        await notify([t["assigned_by"]], "TASK_BLOCKED", f"Task {t['number']} is blocked", f"/crs/{t['cr_id']}", body.reason)
    elif action == "unblock":
        if not (owner or is_mgr(u, pr)):
            err(403, "Not allowed")
        to = t.get("prev_status") or "ASSIGNED"
        t2 = await guarded("cr_tasks", task_id, ["BLOCKED"], {"status": to})
    elif action == "cancel":
        if not is_mgr(u, pr):
            err(403, "Only managers can cancel tasks")
        to = "CANCELLED"
        t2 = await guarded("cr_tasks", task_id, ["ASSIGNED", "IN_DEVELOPMENT", "DEVELOPMENT_COMPLETED", "SIT_IN_PROGRESS", "SIT_FAILED", "BLOCKED", "SIT_PASSED"], {"status": to})
    elif action == "update":
        if not owner:
            err(403, "Only the task developer can update")
        to = t["status"]
        t2 = await guarded("cr_tasks", task_id, None, sets)
    else:
        err(400, "Unknown action")
    if to != t["status"]:
        await audit(u, "TASK_STATUS_CHANGED", "task", task_id, t["project_id"], {"status": t["status"]}, {"status": to}, body.reason or body.notes, meta={"cr_id": t["cr_id"]})
    await recompute_cr(t["cr_id"], u)
    return t2
