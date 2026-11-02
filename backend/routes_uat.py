from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core import (db, now, uid, err, audit, notify, guarded, current_user, my_project_ids, pscope, require_project,
                  member_role, next_number, project_users, users_map, is_admin, MANAGERS, DEV_EXEC, UAT_ROLES, BA_ROLES)
from workflow import set_cr_status, recompute_cr, BUG_CLOSED

router = APIRouter(prefix="/api")


class UatAction(BaseModel):
    comment: Optional[str] = None
    title: Optional[str] = None
    result: Optional[str] = None
    evidence: Optional[str] = None
    reason: Optional[str] = None
    responsible_id: Optional[str] = None
    expected_date: Optional[str] = None


class BugIn(BaseModel):
    cr_id: str
    uat_assignment_id: Optional[str] = None
    title: str
    description: str = ""
    steps: str = ""
    expected: str = ""
    actual: str = ""
    severity: str = "Medium"
    priority: str = "Medium"
    module_id: Optional[str] = None
    screen_id: Optional[str] = None
    blocking: Optional[bool] = None
    attachments: List[dict] = []


class BugAction(BaseModel):
    developer_id: Optional[str] = None
    due_date: Optional[str] = None
    comment: Optional[str] = None
    fix_notes: Optional[str] = None
    evidence: Optional[str] = None


async def _uat_role(u, project_id):
    pr = await require_project(u, project_id)
    if pr not in UAT_ROLES:
        err(403, "Only UAT team members can perform UAT actions")
    return pr


@router.get("/uat/assignments")
async def list_uat(u=Depends(current_user), status: str = "", project_id: str = ""):
    f = pscope(await my_project_ids(u))
    if status:
        f["status"] = {"$in": status.split(",")}
    if project_id:
        f["project_id"] = project_id
    items = await db.uat_assignments.find(f, {"_id": 0}).sort("updated_at", -1).to_list(500)
    for a in items:
        a["open_bugs"] = await db.bugs.count_documents({"cr_id": a["cr_id"], "status": {"$nin": list(BUG_CLOSED)}})
    return items


@router.post("/uat/assignments/{aid}/action/{action}")
async def uat_action(aid: str, action: str, body: UatAction, u=Depends(current_user)):
    a = await db.uat_assignments.find_one({"id": aid}, {"_id": 0})
    if not a:
        err(404, "Not found")
    await _uat_role(u, a["project_id"])
    cr = await db.change_requests.find_one({"id": a["cr_id"]}, {"_id": 0}) if a.get("cr_id") else None
    st = a["status"]
    if action == "start":
        if st == "PENDING":
            a = await guarded("uat_assignments", aid, ["PENDING"], {"status": "IN_PROGRESS", "started_at": now(), "started_by": u["name"]})
        elif st == "RETEST_PENDING":
            a = await guarded("uat_assignments", aid, ["RETEST_PENDING"], {"status": "RETEST_IN_PROGRESS"})
            await db.bugs.update_many({"id": {"$in": a["retest_bug_ids"]}, "status": "UAT_DEPLOYED"}, {"$set": {"status": "RETEST_IN_PROGRESS"}})
        else:
            err(409, "Testing already started")
        if cr and cr["status"] == "UAT_DEPLOYED" and a["scope"] != "partial":
            await set_cr_status(cr, "UAT_IN_PROGRESS", u, "UAT started")
    elif action == "add_case":
        if st not in ("IN_PROGRESS", "RETEST_IN_PROGRESS"):
            err(409, "Start testing first")
        if not body.title or body.result not in ("PASS", "FAIL", "BLOCKED"):
            err(400, "Test case title and result (PASS/FAIL/BLOCKED) required")
        case = {"id": uid(), "title": body.title, "result": body.result, "evidence": body.evidence, "by": u["name"], "at": now()}
        a = await guarded("uat_assignments", aid, [st], {}, push={"test_cases": case})
        await audit(u, "UAT_TEST_RESULT", "uat", aid, a["project_id"], None, case, meta={"cr_id": a["cr_id"]})
        return a
    elif action == "pass":
        if st not in ("IN_PROGRESS", "RETEST_IN_PROGRESS"):
            err(409, "Testing must be in progress")
        if await db.bugs.count_documents({"cr_id": a["cr_id"], "status": {"$nin": list(BUG_CLOSED)}}):
            err(409, "Open bugs must be verified before UAT can pass")
        if not a.get("test_cases"):
            err(400, "Record at least one test case result")
        a = await guarded("uat_assignments", aid, [st], {"status": "PASSED" if st == "IN_PROGRESS" else "RETEST_PASSED", "completed_at": now(), "comment": body.comment})
        if cr and cr["status"] in ("UAT_IN_PROGRESS", "UAT_DEPLOYED"):
            unreleased = await db.cr_tasks.count_documents({"cr_id": cr["id"], "status": {"$nin": ["READY_FOR_UAT", "CANCELLED"]}, "mandatory": {"$ne": False}})
            if not unreleased:
                await set_cr_status(cr, "UAT_PASSED", u, body.comment or "UAT acceptance passed")
                await notify([cr.get("ba_id")], "UAT_PASSED", f"{cr['number']} passed UAT — ready for business closure", f"/crs/{cr['id']}")
    elif action == "fail":
        if st not in ("IN_PROGRESS", "RETEST_IN_PROGRESS"):
            err(409, "Testing must be in progress")
        if not body.comment:
            err(400, "Failure comment required")
        a = await guarded("uat_assignments", aid, [st], {"status": "FAILED", "comment": body.comment})
        if cr and cr["status"] in ("UAT_IN_PROGRESS", "UAT_DEPLOYED", "UAT_HOLD"):
            await set_cr_status(cr, "UAT_FAILED", u, body.comment)
        await notify([cr.get("ba_id"), cr.get("manager_id")] if cr else [], "UAT_FAILED", f"UAT failed for {a['cr_number']}", f"/crs/{a['cr_id']}", body.comment)
    elif action == "hold":
        if st not in ("PENDING", "IN_PROGRESS", "RETEST_PENDING", "RETEST_IN_PROGRESS"):
            err(409, "Cannot hold in this state")
        if not (body.reason and body.responsible_id and body.expected_date):
            err(400, "Hold reason, responsible user and expected date are required")
        hold = {"id": uid(), "uat_assignment_id": aid, "project_id": a["project_id"], "cr_id": a["cr_id"], "reason": body.reason, "responsible_id": body.responsible_id,
                "expected_date": body.expected_date, "notes": body.comment, "by": u["id"], "by_name": u["name"], "status": "ACTIVE", "at": now()}
        await db.uat_holds.insert_one(dict(hold))
        a = await guarded("uat_assignments", aid, [st], {"status": "ON_HOLD", "prev_status": st, "hold": {k: hold[k] for k in ("reason", "responsible_id", "expected_date", "notes", "by_name", "at")}})
        if cr and cr["status"] in ("UAT_IN_PROGRESS", "UAT_DEPLOYED"):
            await set_cr_status(cr, "UAT_HOLD", u, body.reason)
        bas = await project_users(a["project_id"], BA_ROLES)
        await notify([body.responsible_id] + bas, "UAT_HOLD", f"UAT hold on {a['cr_number']}", f"/crs/{a['cr_id']}", f"{body.reason} (expected {body.expected_date})")
    elif action == "resume":
        if st != "ON_HOLD":
            err(409, "Not on hold")
        back = a.get("prev_status") or "IN_PROGRESS"
        a = await guarded("uat_assignments", aid, ["ON_HOLD"], {"status": back})
        await db.uat_holds.update_many({"uat_assignment_id": aid, "status": "ACTIVE"}, {"$set": {"status": "RESOLVED", "resolved_at": now(), "resolved_by": u["name"]}})
        if cr and cr["status"] == "UAT_HOLD":
            await set_cr_status(cr, "UAT_IN_PROGRESS", u, "UAT hold resolved")
        await notify(await project_users(a["project_id"], BA_ROLES), "UAT_HOLD_RESOLVED", f"UAT hold resolved on {a['cr_number']}", f"/crs/{a['cr_id']}")
    else:
        err(400, "Unknown action")
    await audit(u, f"UAT_{action.upper()}", "uat", aid, a["project_id"], {"status": st}, {"status": a["status"]}, body.comment or body.reason, meta={"cr_id": a["cr_id"]})
    return a


@router.get("/bugs")
async def list_bugs(u=Depends(current_user), status: str = "", project_id: str = "", mine: bool = False, severity: str = "", cr_id: str = ""):
    f = pscope(await my_project_ids(u))
    for k, v in [("status", status), ("severity", severity)]:
        if v:
            f[k] = {"$in": v.split(",")}
    if project_id:
        f["project_id"] = project_id
    if cr_id:
        f["cr_id"] = cr_id
    if mine:
        f["developer_id"] = u["id"]
    items = await db.bugs.find(f, {"_id": 0}).sort("updated_at", -1).to_list(1000)
    um = await users_map([b.get("developer_id") for b in items])
    for b in items:
        b["developer_name"] = um.get(b.get("developer_id"), {}).get("name")
    return items


@router.post("/bugs")
async def create_bug(body: BugIn, u=Depends(current_user)):
    cr = await db.change_requests.find_one({"id": body.cr_id}, {"_id": 0})
    if not cr:
        err(404, "CR not found")
    pr = await require_project(u, cr["project_id"])
    if not (pr in UAT_ROLES or pr in BA_ROLES or is_admin(u)):
        err(403, "Only UAT or BA can report bugs")
    a = await db.uat_assignments.find_one({"id": body.uat_assignment_id}, {"_id": 0}) if body.uat_assignment_id else None
    if a and a["cr_id"] != body.cr_id:
        err(400, "UAT assignment does not belong to this CR")
    b = {**body.model_dump(), "id": uid(), "number": await next_number("BUG"), "project_id": cr["project_id"], "cr_number": cr["number"],
         "srn_id": None, "found_in_srn_id": a["srn_id"] if a else None, "found_in_srn_number": a["srn_number"] if a else None,
         "deployment_id": a["deployment_id"] if a else None, "blocking": body.blocking if body.blocking is not None else body.severity in ("Critical", "High"),
         "status": "OPEN", "reported_by": u["id"], "reported_by_name": u["name"], "developer_id": None, "assigned_by": None,
         "due_date": None, "fix_notes": "", "history": [{"to": "OPEN", "by": u["name"], "at": now()}], "created_at": now(), "updated_at": now(), "version": 1}
    await db.bugs.insert_one(dict(b))
    await audit(u, "BUG_CREATED", "bug", b["id"], cr["project_id"], None, {"number": b["number"], "severity": b["severity"]}, meta={"cr_id": cr["id"]})
    await notify([cr.get("manager_id")] + await project_users(cr["project_id"], {"pm", "team_lead"}), "BUG_CREATED", f"New UAT bug {b['number']}: {b['title']}", f"/bugs?id={b['id']}")
    b.pop("_id", None)
    return b


BUG_DEV_FLOW = {
    "start": (["ASSIGNED", "SIT_FAILED"], "IN_DEVELOPMENT"),
    "fixed": (["IN_DEVELOPMENT"], "FIXED"),
    "start_sit": (["FIXED"], "SIT_IN_PROGRESS"),
    "sit_pass": (["SIT_IN_PROGRESS"], "SIT_PASSED"),
    "sit_fail": (["SIT_IN_PROGRESS"], "SIT_FAILED"),
}


@router.post("/bugs/{bid}/action/{action}")
async def bug_action(bid: str, action: str, body: BugAction, u=Depends(current_user)):
    b = await db.bugs.find_one({"id": bid}, {"_id": 0})
    if not b:
        err(404, "Bug not found")
    pr = await require_project(u, b["project_id"])
    st = b["status"]
    sets = {}
    if action == "assign":
        if not (pr in MANAGERS or is_admin(u)):
            err(403, "Only PM / Team Lead can assign bugs")
        if not body.developer_id or (await member_role({"id": body.developer_id}, b["project_id"])) not in DEV_EXEC:
            err(400, "Select a developer on this project")
        frm, to = ["OPEN", "REOPENED", "ASSIGNED"], "ASSIGNED"
        sets = {"developer_id": body.developer_id, "assigned_by": u["id"], "due_date": body.due_date}
        await db.bug_assignments.insert_one({"id": uid(), "bug_id": bid, "developer_id": body.developer_id, "by": u["id"], "at": now()})
        await notify([body.developer_id], "BUG_ASSIGNED", f"Bug {b['number']} assigned to you", f"/bugs?id={bid}")
    elif action in BUG_DEV_FLOW:
        if u["id"] != b.get("developer_id"):
            err(403, "Only the assigned developer can do this")
        frm, to = BUG_DEV_FLOW[action]
        if action == "fixed":
            if not body.fix_notes:
                err(400, "Fix notes required")
            sets["fix_notes"] = body.fix_notes
            await db.bug_fix_history.insert_one({"id": uid(), "bug_id": bid, "notes": body.fix_notes, "by": u["name"], "at": now()})
            await notify([b.get("assigned_by")], "BUG_FIXED", f"Bug {b['number']} fixed (pending SIT)", f"/bugs?id={bid}")
        if action in ("sit_pass", "sit_fail"):
            if not body.evidence:
                err(400, "SIT evidence required")
            sets["sit_result"] = {"result": "PASS" if action == "sit_pass" else "FAIL", "evidence": body.evidence, "at": now()}
    elif action in ("retest_start", "verify", "reopen", "close"):
        if not (pr in UAT_ROLES or (action == "close" and pr in BA_ROLES)):
            err(403, "Only UAT can retest and verify bugs")
        frm, to = {"retest_start": (["UAT_DEPLOYED"], "RETEST_IN_PROGRESS"), "verify": (["RETEST_IN_PROGRESS"], "VERIFIED"),
                   "reopen": (["RETEST_IN_PROGRESS", "VERIFIED"], "REOPENED"), "close": (["VERIFIED"], "CLOSED")}[action]
        if action in ("verify", "reopen"):
            if action == "reopen" and not body.comment:
                err(400, "Reopen reason required")
            await db.bug_verifications.insert_one({"id": uid(), "bug_id": bid, "result": to, "comment": body.comment, "by": u["name"], "at": now()})
            sets["uat_verification"] = {"result": to, "comment": body.comment, "by": u["name"], "at": now()}
        if action == "reopen":
            sets.update({"srn_id": None, "reopen_count": b.get("reopen_count", 0) + 1})
            await notify([b.get("developer_id"), b.get("assigned_by")], "BUG_REOPENED", f"Bug {b['number']} reopened", f"/bugs?id={bid}", body.comment)
    else:
        err(400, "Unknown action")
    b2 = await guarded("bugs", bid, frm, {**sets, "status": to}, push={"history": {"from": st, "to": to, "by": u["name"], "at": now(), "comment": body.comment}})
    await audit(u, "BUG_STATUS_CHANGED", "bug", bid, b["project_id"], {"status": st}, {"status": to}, body.comment or body.fix_notes, meta={"cr_id": b["cr_id"]})
    if b.get("blocking"):
        await recompute_cr(b["cr_id"], u)
    return b2
