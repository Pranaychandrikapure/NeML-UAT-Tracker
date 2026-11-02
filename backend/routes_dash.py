import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core import db, current_user, my_project_ids, pscope, is_admin, users_map, MANAGERS, BA_ROLES, UAT_ROLES, DEV_EXEC
from routes_release import can_approve

router = APIRouter(prefix="/api")
DONE = ["CLOSED", "CANCELLED"]


def _filters(pids, project_id, priority, source, ba_id, manager_id, date_from, date_to):
    f = pscope(pids)
    if project_id:
        f["project_id"] = project_id if pids is None or project_id in pids else "__none__"
    for k, v in [("priority", priority), ("source", source), ("ba_id", ba_id), ("manager_id", manager_id)]:
        if v:
            f[k] = v
    if date_from or date_to:
        f["created_at"] = {k: v for k, v in [("$gte", date_from), ("$lte", (date_to + "T23:59:59") if date_to else "")] if v}
    return f


@router.get("/dashboard")
async def dashboard(u=Depends(current_user), project_id: str = "", priority: str = "", source: str = "", ba_id: str = "",
                    manager_id: str = "", date_from: str = "", date_to: str = ""):
    pids = await my_project_ids(u)
    f = _filters(pids, project_id, priority, source, ba_id, manager_id, date_from, date_to)
    pf = {k: v for k, v in f.items() if k == "project_id"}
    today = datetime.now(timezone.utc).date().isoformat()
    cnt = lambda extra: db.change_requests.count_documents({**f, **extra})
    kpis = {
        "crs_pending_approval": await cnt({"status": {"$in": ["NEW", "BA_REVIEW", "DEADLINE_APPROVAL_PENDING"]}}),
        "development_pending": await cnt({"status": {"$in": ["IMPACT_ANALYSIS", "ASSIGNED", "IN_DEVELOPMENT"]}}),
        "sit_pending": await cnt({"status": "SIT_IN_PROGRESS"}),
        "ready_for_uat": await cnt({"status": "READY_FOR_UAT"}),
        "srn_approval_pending": await db.srns.count_documents({**pf, "status": {"$in": ["IN_REVIEW", "ON_HOLD"]}}),
        "uat_deployment_pending": await cnt({"status": "UAT_DEPLOYMENT_PENDING"}),
        "uat_pending": await cnt({"status": {"$in": ["UAT_DEPLOYED", "UAT_IN_PROGRESS"]}}),
        "uat_hold": await cnt({"status": "UAT_HOLD"}),
        "high_priority": await cnt({"priority": {"$in": ["High", "Critical"]}, "status": {"$nin": DONE}}),
        "open_bugs": await db.bugs.count_documents({**pf, "status": {"$nin": ["VERIFIED", "CLOSED"]}}),
        "overdue": await cnt({"status": {"$nin": DONE + ["UAT_PASSED", "DRAFT"]}, "$or": [{"approved_deadline": {"$lt": today, "$ne": None}},
                                                                                           {"approved_deadline": None, "requested_deadline": {"$lt": today, "$ne": None}}]}),
        "completed": await cnt({"status": "CLOSED"}),
    }
    mpids = await db.project_members.find({"user_id": u["id"]}, {"_id": 0}).to_list(200)
    proles = {m["project_role"] for m in mpids} | {u["role"]}
    actions = []
    add = lambda kind, title, sub, link: actions.append({"kind": kind, "title": title, "subtitle": sub, "link": link})
    if proles & BA_ROLES or is_admin(u):
        q = {**pf, **pscope(pids), "status": {"$in": ["NEW", "BA_REVIEW"]}}
        if not is_admin(u) and "ba_lead" not in proles:
            q["ba_id"] = u["id"]
        for c in await db.change_requests.find(q, {"_id": 0, "id": 1, "number": 1, "title": 1, "status": 1}).to_list(50):
            add("BA_VALIDATION", f"Validate {c['number']}", c["title"], f"/crs/{c['id']}")
        for d in await db.deadline_requests.find({**pscope(pids), "status": "PENDING"}, {"_id": 0}).to_list(50):
            add("DEADLINE_DECISION", f"Deadline revision on {d['cr_number']}", f"Proposed {d['proposed_deadline']} by {d['requested_by_name']}", f"/crs/{d['cr_id']}")
        for c in await db.change_requests.find({**pscope(pids), "status": "UAT_PASSED"}, {"_id": 0, "id": 1, "number": 1, "title": 1}).to_list(50):
            add("BUSINESS_CLOSURE", f"Close {c['number']}", "UAT passed — grant business acceptance", f"/crs/{c['id']}")
    if proles & MANAGERS:
        for c in await db.change_requests.find({**pscope(pids), "manager_id": u["id"], "status": {"$in": ["IMPACT_ANALYSIS"]}}, {"_id": 0, "id": 1, "number": 1, "title": 1}).to_list(50):
            add("IMPACT_ANALYSIS", f"Analyse & assign {c['number']}", c["title"], f"/crs/{c['id']}")
        for b in await db.bugs.find({**pscope(pids), "status": {"$in": ["OPEN", "REOPENED"]}}, {"_id": 0, "id": 1, "number": 1, "title": 1}).to_list(50):
            add("BUG_ASSIGN", f"Assign bug {b['number']}", b["title"], f"/bugs?id={b['id']}")
        for s in await db.srns.find({**pscope(pids), "status": {"$in": ["APPROVED", "DEPLOYMENT_PENDING", "DEPLOYMENT_IN_PROGRESS", "DEPLOYMENT_FAILED"]}}, {"_id": 0, "id": 1, "number": 1, "status": 1}).to_list(50):
            add("DEPLOYMENT", f"Deploy {s['number']}", s["status"].replace("_", " ").title(), f"/srns/{s['id']}")
    for s in await db.srns.find({**pscope(pids), "status": "IN_REVIEW"}, {"_id": 0}).to_list(200):
        if (await can_approve(u, s))[0]:
            add("SRN_APPROVAL", f"Review SRN {s['number']}", s.get("release_version", ""), f"/srns/{s['id']}")
    for s in await db.srns.find({"author_id": u["id"], "status": {"$in": ["REJECTED", "CHANGES_REQUESTED", "DRAFT"]}}, {"_id": 0, "id": 1, "number": 1, "status": 1}).to_list(50):
        add("SRN_REWORK", f"Update SRN {s['number']}", s["status"].replace("_", " ").title(), f"/srns/{s['id']}")
    for t in await db.cr_tasks.find({"developer_id": u["id"], "status": {"$in": ["ASSIGNED", "IN_DEVELOPMENT", "DEVELOPMENT_COMPLETED", "SIT_IN_PROGRESS", "SIT_FAILED"]}}, {"_id": 0}).to_list(50):
        add("TASK", f"{t['number']} · {t['title']}", t["status"].replace("_", " ").title(), f"/crs/{t['cr_id']}")
    for b in await db.bugs.find({"developer_id": u["id"], "status": {"$in": ["ASSIGNED", "IN_DEVELOPMENT", "FIXED", "SIT_IN_PROGRESS", "SIT_FAILED"]}}, {"_id": 0}).to_list(50):
        add("BUG_FIX", f"Fix {b['number']}", b["title"], f"/bugs?id={b['id']}")
    if proles & UAT_ROLES:
        for a in await db.uat_assignments.find({**pscope(pids), "status": {"$in": ["PENDING", "RETEST_PENDING", "IN_PROGRESS", "RETEST_IN_PROGRESS"]}}, {"_id": 0}).to_list(50):
            add("UAT", f"UAT {a['cr_number']} ({a['srn_number']})", a["status"].replace("_", " ").title(), "/uat")
    upcoming = await db.change_requests.find({**f, "status": {"$nin": DONE + ["UAT_PASSED"]}, "$or": [{"approved_deadline": {"$gte": today}}, {"requested_deadline": {"$gte": today}}]},
                                             {"_id": 0, "id": 1, "number": 1, "title": 1, "approved_deadline": 1, "requested_deadline": 1, "status": 1, "priority": 1}).sort("requested_deadline", 1).to_list(8)
    my_crs = await db.change_requests.find({**pscope(pids), "status": {"$nin": DONE}, "$or": [{"ba_id": u["id"]}, {"manager_id": u["id"]}, {"id": {"$in": await db.cr_tasks.distinct("cr_id", {"developer_id": u["id"]})}}]},
                                           {"_id": 0, "id": 1, "number": 1, "title": 1, "status": 1, "priority": 1}).sort("updated_at", -1).to_list(10)
    deployments = await db.deployments.find(pf or pscope(pids), {"_id": 0}).sort("created_at", -1).to_list(6)
    bugs = await db.bugs.find({**(pf or pscope(pids)), "status": {"$nin": ["VERIFIED", "CLOSED"]}}, {"_id": 0, "id": 1, "number": 1, "title": 1, "severity": 1, "status": 1}).sort("created_at", -1).to_list(6)
    activity = await db.audit_logs.find({**(pf or pscope(pids)), "action": {"$ne": "LOGIN"}}, {"_id": 0}).sort("at", -1).to_list(12)
    releases = await db.srns.find({**(pf or pscope(pids)), "status": "UAT_DEPLOYED"}, {"_id": 0, "id": 1, "number": 1, "release_version": 1, "deployed_at": 1}).sort("deployed_at", -1).to_list(6)
    by_status = await db.change_requests.aggregate([{"$match": f}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}]).to_list(50)
    return {"kpis": kpis, "pending_actions": actions[:40], "upcoming_deadlines": upcoming, "my_crs": my_crs, "deployments": deployments,
            "open_bugs": bugs, "recent_activity": activity, "release_history": releases, "by_status": {x["_id"]: x["n"] for x in by_status}}


@router.get("/notifications")
async def notifications(u=Depends(current_user)):
    items = await db.notifications.find({"user_id": u["id"]}, {"_id": 0}).sort("at", -1).to_list(50)
    unread = await db.notifications.count_documents({"user_id": u["id"], "read": False})
    return {"items": items, "unread": unread}


class ReadIn(BaseModel):
    ids: list = []


@router.post("/notifications/read")
async def mark_read(body: ReadIn, u=Depends(current_user)):
    q = {"user_id": u["id"]}
    if body.ids:
        q["id"] = {"$in": body.ids}
    await db.notifications.update_many(q, {"$set": {"read": True}})
    return {"ok": True}


@router.get("/audit")
async def audit_list(u=Depends(current_user), entity_type: str = "", action: str = "", limit: int = 200):
    f = {} if is_admin(u) else {"project_id": {"$in": await my_project_ids(u)}}
    if entity_type:
        f["entity_type"] = entity_type
    if action:
        f["action"] = {"$regex": re.escape(action), "$options": "i"}
    return await db.audit_logs.find(f, {"_id": 0}).sort("at", -1).to_list(min(limit, 1000))


@router.get("/search")
async def search(q: str, u=Depends(current_user)):
    pf = pscope(await my_project_ids(u))
    rx = {"$regex": re.escape(q), "$options": "i"}
    crs = await db.change_requests.find({**pf, "$or": [{"number": rx}, {"title": rx}]}, {"_id": 0, "id": 1, "number": 1, "title": 1}).to_list(8)
    srns = await db.srns.find({**pf, "$or": [{"number": rx}, {"release_version": rx}]}, {"_id": 0, "id": 1, "number": 1, "release_version": 1}).to_list(5)
    bugs = await db.bugs.find({**pf, "$or": [{"number": rx}, {"title": rx}]}, {"_id": 0, "id": 1, "number": 1, "title": 1}).to_list(5)
    return {"crs": crs, "srns": srns, "bugs": bugs}


def _hours(a, b):
    try:
        return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 3600
    except (TypeError, ValueError):
        return None


@router.get("/reports")
async def reports(u=Depends(current_user), project_id: str = ""):
    pids = await my_project_ids(u)
    f = pscope(pids)
    if project_id:
        f["project_id"] = project_id if pids is None or project_id in pids else "__none__"
    crs = await db.change_requests.find(f, {"_id": 0, "comments": 0}).to_list(10000)
    projs = {p["id"]: p["name"] for p in await db.projects.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(1000)}
    by_month, by_project, by_priority, slips = {}, {}, {}, []
    for c in crs:
        by_month[c["created_at"][:7]] = by_month.get(c["created_at"][:7], 0) + 1
        by_project[projs.get(c["project_id"], "?")] = by_project.get(projs.get(c["project_id"], "?"), 0) + 1
        by_priority[c.get("priority", "Medium")] = by_priority.get(c.get("priority", "Medium"), 0) + 1
        if c.get("approved_deadline") and c.get("requested_deadline") and c["approved_deadline"] > c["requested_deadline"]:
            slips.append({"cr": c["number"], "requested": c["requested_deadline"], "approved": c["approved_deadline"]})
    tasks = await db.cr_tasks.find(f, {"_id": 0}).to_list(20000)
    sit = await db.task_sit_results.find({"task_id": {"$in": [t["id"] for t in tasks]}}, {"_id": 0, "result": 1}).to_list(50000)
    uat = await db.uat_assignments.find(f, {"_id": 0, "status": 1}).to_list(20000)
    bugs = await db.bugs.find(f, {"_id": 0}).to_list(20000)
    sev = {}
    for b in bugs:
        if b["status"] not in ("VERIFIED", "CLOSED"):
            sev[b["severity"]] = sev.get(b["severity"], 0) + 1
    res_times = [h for b in bugs if b["status"] in ("VERIFIED", "CLOSED") for h in [_hours(b["created_at"], b.get("updated_at"))] if h]
    dev_dur = [h for c in crs for h in [_hours(next((x["at"] for x in c.get("status_history", []) if x["to"] == "ASSIGNED"), None),
                                                   next((x["at"] for x in c.get("status_history", []) if x["to"] == "READY_FOR_UAT"), None))] if h]
    approvals = await db.srn_approvals.find({"decision": "APPROVE"}, {"_id": 0, "srn_id": 1, "at": 1}).to_list(20000)
    srns = {s["id"]: s for s in await db.srns.find(f, {"_id": 0, "id": 1, "submitted_at": 1, "deployed_at": 1}).to_list(10000)}
    turn = [h for a in approvals if a["srn_id"] in srns for h in [_hours(srns[a["srn_id"]].get("submitted_at"), a["at"])] if h is not None]
    freq = {}
    for s in srns.values():
        if s.get("deployed_at"):
            freq[s["deployed_at"][:7]] = freq.get(s["deployed_at"][:7], 0) + 1
    um = await users_map([t["developer_id"] for t in tasks])
    wl = {}
    for t in tasks:
        if t["status"] not in ("READY_FOR_UAT", "CANCELLED", "SIT_PASSED"):
            n = um.get(t["developer_id"], {}).get("name", "?")
            wl[n] = wl.get(n, 0) + 1
    holds = await db.uat_holds.find(f, {"_id": 0, "reason": 1, "status": 1, "at": 1}).to_list(1000)
    pl = {}
    for c in crs:
        if c["status"] not in DONE:
            n = projs.get(c["project_id"], "?")
            pl[n] = pl.get(n, 0) + 1
    avg = lambda xs: round(sum(xs) / len(xs), 1) if xs else None
    series = lambda d: [{"name": k, "value": v} for k, v in sorted(d.items())]
    return {
        "basis": {"current_state": ["crs_by_project", "crs_by_priority", "open_bugs_by_severity", "developer_workload", "project_workload", "development_pending", "srn_approvals_pending"],
                  "historical": ["crs_by_month", "avg_dev_hours", "sit_failure_rate", "uat_rejection_rate", "avg_bug_resolution_hours", "approval_turnaround_hours", "release_frequency", "deadline_slippages", "uat_holds"]},
        "crs_by_month": series(by_month), "crs_by_project": series(by_project), "crs_by_priority": series(by_priority),
        "development_pending": sum(1 for c in crs if c["status"] in ("IMPACT_ANALYSIS", "ASSIGNED", "IN_DEVELOPMENT", "SIT_IN_PROGRESS")),
        "avg_dev_hours": avg(dev_dur),
        "sit_failure_rate": round(100 * sum(1 for s in sit if s["result"] == "FAIL") / len(sit), 1) if sit else None,
        "uat_rejection_rate": round(100 * sum(1 for a in uat if a["status"] == "FAILED") / len(uat), 1) if uat else None,
        "open_bugs_by_severity": series(sev), "avg_bug_resolution_hours": avg(res_times),
        "srn_approvals_pending": await db.srns.count_documents({**f, "status": {"$in": ["IN_REVIEW", "ON_HOLD"]}}),
        "approval_turnaround_hours": avg(turn), "deadline_slippages": slips, "uat_holds": holds,
        "release_frequency": series(freq), "project_workload": series(pl), "developer_workload": series(wl),
    }
