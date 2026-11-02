from core import db, now, audit, notify, guarded, project_users, BA_ROLES, MANAGERS

CR_DEV_PHASE = {"ASSIGNED", "IN_DEVELOPMENT", "SIT_IN_PROGRESS", "READY_FOR_UAT"}
BUG_CLOSED = {"VERIFIED", "CLOSED"}
TASK_DONE = {"SIT_PASSED", "READY_FOR_UAT"}


async def set_cr_status(cr, to, u, comment=None, extra=None):
    if cr["status"] == to and not extra:
        return cr
    doc = await guarded("change_requests", cr["id"], [cr["status"]], {"status": to, **(extra or {})},
                        push={"status_history": {"from": cr["status"], "to": to, "by": u["id"], "by_name": u["name"], "at": now(), "comment": comment}})
    if cr["status"] != to:
        await audit(u, "CR_STATUS_CHANGED", "cr", cr["id"], cr["project_id"], {"status": cr["status"]}, {"status": to}, comment)
    return doc


async def recompute_cr(cr_id, u):
    """Derive CR development status from its mandatory tasks and blocking bugs."""
    cr = await db.change_requests.find_one({"id": cr_id}, {"_id": 0})
    if not cr or cr["status"] not in CR_DEV_PHASE:
        return cr
    tasks = await db.cr_tasks.find({"cr_id": cr_id, "status": {"$ne": "CANCELLED"}, "mandatory": {"$ne": False}}, {"_id": 0}).to_list(500)
    if not tasks:
        return cr
    sts = [t["status"] for t in tasks]
    blocking = await db.bugs.count_documents({"cr_id": cr_id, "blocking": True, "status": {"$nin": list(BUG_CLOSED)}})
    if all(s in TASK_DONE for s in sts) and not blocking:
        to = "READY_FOR_UAT"
    elif any(s in ("IN_DEVELOPMENT", "SIT_FAILED", "BLOCKED") for s in sts):
        to = "IN_DEVELOPMENT"
    elif any(s in ("DEVELOPMENT_COMPLETED", "SIT_IN_PROGRESS") or s in TASK_DONE for s in sts):
        to = "SIT_IN_PROGRESS"
    else:
        to = "ASSIGNED"
    if to != cr["status"]:
        cr = await set_cr_status(cr, to, u, "Automatic status from task progress")
        if to == "READY_FOR_UAT":
            await notify([cr.get("ba_id"), cr.get("manager_id")], "CR_READY_FOR_UAT",
                         f"{cr['number']} is Ready for UAT", f"/crs/{cr_id}", "All mandatory tasks passed SIT.")
    return cr


async def cr_ba_ids(cr):
    return [cr.get("ba_id")] + await project_users(cr["project_id"], {"ba_lead"})


def is_ba(u, pr):
    return u["role"] in BA_ROLES or pr in BA_ROLES or u["role"] == "system_admin"


def is_mgr(u, pr):
    return u["role"] in MANAGERS or pr in MANAGERS or u["role"] == "system_admin"
