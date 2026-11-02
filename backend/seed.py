import os
from datetime import datetime, timedelta, timezone

from core import db, now, uid, DEFAULT_PROJECT_CONFIG, DEFAULT_TECH, DEMO_MODE


def _d(days):
    return (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()


DEMO_USERS = [
    ("lead", "Priya Sharma (Demo)", "project_lead", "admin"),
    ("spm", "Rahul Mehta (Demo)", "senior_pm", "lead"),
    ("pm", "Anita Desai (Demo)", "pm", "spm"),
    ("tl", "Vikram Rao (Demo)", "team_lead", "pm"),
    ("dev1", "Komal Velukar (Demo)", "developer", "tl"),
    ("dev2", "Satyam Wanjari (Demo)", "developer", "pm"),
    ("dev3", "Rupali Poundekar (Demo)", "developer", "pm"),
    ("balead", "Harshal Giri (Demo)", "ba_lead", "admin"),
    ("ba", "Sneha Kulkarni (Demo)", "ba", "balead"),
    ("uatlead", "Rajat Bodankar (Demo)", "uat_lead", "admin"),
    ("uatmgr", "Meera Iyer (Demo)", "uat_manager", "uatlead"),
    ("uat", "Arjun Nair (Demo)", "uat_member", "uatmgr"),
]


async def ensure_indexes():
    await db.users.create_index("id", unique=True)
    await db.users.create_index("email", unique=True)
    await db.projects.create_index("id", unique=True)
    await db.projects.create_index("zoho_id", sparse=True)
    await db.project_members.create_index([("project_id", 1), ("user_id", 1)], unique=True)
    await db.change_requests.create_index("id", unique=True)
    await db.change_requests.create_index([("source", 1), ("external_id", 1)], unique=True, partialFilterExpression={"external_id": {"$type": "string"}})
    for k in ("status", "project_id", "ba_id", "manager_id", "requested_deadline", "approved_deadline"):
        await db.change_requests.create_index(k)
    await db.cr_tasks.create_index("id", unique=True)
    await db.cr_tasks.create_index([("cr_id", 1), ("status", 1)])
    await db.cr_tasks.create_index("developer_id")
    await db.modules.create_index([("project_id", 1), ("name", 1)], unique=True)
    await db.screens.create_index([("module_id", 1), ("name", 1)], unique=True)
    await db.srns.create_index("id", unique=True)
    await db.bugs.create_index("id", unique=True)
    await db.email_messages.create_index("idempotency_key", unique=True)
    await db.notifications.create_index([("user_id", 1), ("read", 1)])
    await db.notifications.create_index("dedupe", sparse=True)
    await db.audit_logs.create_index([("entity_id", 1), ("at", -1)])


async def seed():
    await ensure_indexes()
    for t in DEFAULT_TECH:
        await db.tech_options.update_one({"name": t}, {"$set": {"name": t}}, upsert=True)
    admin_email = os.environ.get("ADMIN_EMAIL", "").split(",")[0].strip().lower()
    admin = await db.users.find_one({"email": admin_email}, {"_id": 0}) if admin_email else None
    if admin_email and not admin:
        admin = {"id": uid(), "email": admin_email, "name": admin_email.split("@")[0].title(), "role": "system_admin",
                 "reporting_manager_id": None, "department": "Administration", "active": True, "is_demo": False, "notify_email": True, "created_at": now()}
        await db.users.insert_one(dict(admin))
    if not DEMO_MODE or await db.settings.find_one({"key": "demo_seeded"}):
        return
    ids = {"admin": admin["id"] if admin else None}
    for key, name, role, mgr in DEMO_USERS:
        ids[key] = uid()
        await db.users.insert_one({"id": ids[key], "email": f"delivered+{key}@resend.dev", "name": name, "role": role, "reporting_manager_id": ids.get(mgr),
                                   "department": {"dev": "Engineering"}.get("dev") if role in ("project_lead", "senior_pm", "pm", "team_lead", "developer") else ("Business Analysis" if "ba" in role else "UAT"),
                                   "active": True, "is_demo": True, "notify_email": True, "created_at": now(), "can_create_developers": role == "team_lead"})
    projects = {}
    for code, name, tech in [("NAFED", "NAFED V3 Web & Service Application", ["Java", "Spring Boot", "Angular", "PostgreSQL"]),
                             ("ESAM", "e-SAM Auction Platform", ["Python", "FastAPI", "React", "MongoDB"])]:
        pid = uid()
        projects[code] = pid
        await db.projects.insert_one({"id": pid, "zoho_id": None, "code": code, "name": name, "description": f"Demo project — {name}", "owner_name": "Priya Sharma (Demo)",
                                      "start_date": _d(-120), "end_date": _d(240), "status": "Active", "tech_stack": tech, "source": "MANUAL", "is_demo": True,
                                      "config": DEFAULT_PROJECT_CONFIG, "created_at": now(), "updated_at": now()})
    for key, _, role, _ in DEMO_USERS:
        for code in ("NAFED", "ESAM"):
            if key == "dev3" and code == "NAFED" or key == "dev2" and code == "ESAM":
                continue
            await db.project_members.insert_one({"project_id": projects[code], "user_id": ids[key], "project_role": role, "at": now()})
    mods = {}
    for mname, screens in [("Lot Management", ["Lot Entry", "Lot Details", "Lot Upload"]), ("Auction Management", ["Auction Creation", "Auction Approval", "Auction Reports"])]:
        mid = uid()
        mods[mname] = mid
        await db.modules.insert_one({"id": mid, "project_id": projects["NAFED"], "name": mname, "description": "", "archived": False, "status": "ACTIVE", "created_at": now()})
        for s in screens:
            await db.screens.insert_one({"id": uid(), "module_id": mid, "project_id": projects["NAFED"], "name": s, "description": "", "archived": False, "status": "ACTIVE", "created_at": now()})
    year = datetime.now(timezone.utc).year
    samples = [
        ("Farmer lot entry threshold increase", "NEW", "High", 10, None),
        ("Nominee-based lot entry", "BA_REVIEW", "Medium", 20, None),
        ("Auction approval escalation matrix", "IMPACT_ANALYSIS", "High", 15, "pm"),
        ("Lot upload bulk validation", "READY_FOR_UAT", "Critical", 6, "pm"),
    ]
    for i, (title, status, prio, dl, mgr) in enumerate(samples, 1):
        cid = uid()
        mod = mods["Auction Management" if "Auction" in title else "Lot Management"]
        await db.change_requests.insert_one({
            "id": cid, "number": f"CR-{year}-{i:04d}", "title": title, "project_id": projects["NAFED"], "source": "INTERNAL", "external_id": None,
            "description": f"[DEMO DATA] {title}.", "business_requirements": "Sample requirement for demonstration.", "expected_result": "Works as specified.",
            "justification": "Demo", "priority": prio, "requested_deadline": _d(dl), "approved_deadline": _d(dl) if status == "READY_FOR_UAT" else None,
            "business_owner": "NAFED Operations", "ba_id": ids["ba"], "manager_id": ids[mgr] if mgr else None, "impacted_module_ids": [mod], "impacted_screen_ids": [],
            "acceptance_criteria": "All scenarios pass in UAT.", "attachments": [], "impact": {}, "status": status, "revision": 1, "is_demo": True,
            "created_by": ids["ba"], "created_by_name": "Sneha Kulkarni (Demo)", "created_at": now(), "updated_at": now(), "version": 1, "comments": [],
            "status_history": [{"from": None, "to": status, "by": ids["ba"], "by_name": "Seed", "at": now(), "comment": "Demo seed"}]})
        if status == "READY_FOR_UAT":
            for j, (dev, ttl) in enumerate([("dev1", "CSV validation rules"), ("dev2", "Upload error report")], 1):
                await db.cr_tasks.insert_one({"id": uid(), "number": f"T-{year}-{j:04d}", "cr_id": cid, "cr_number": f"CR-{year}-{i:04d}", "project_id": projects["NAFED"],
                                              "title": ttl, "description": "", "developer_id": ids[dev], "collaborator_ids": [], "module_id": mod, "screen_id": None,
                                              "priority": prio, "planned_start": _d(-10), "planned_end": _d(2), "estimated_hours": 16, "actual_hours": 14, "mandatory": True,
                                              "status": "SIT_PASSED", "sit_result": "PASS", "assigned_by": ids["pm"], "assigned_by_name": "Anita Desai (Demo)", "self_assigned": dev == "tl",
                                              "git_ref": f"feature/lot-upload-{j}", "notes": "", "srn_id": None, "created_at": now(), "updated_at": now(), "version": 1, "is_demo": True})
    for name in ("CR", "T"):
        await db.counters.update_one({"_id": f"{name}-{year}"}, {"$max": {"seq": 10}}, upsert=True)
    await db.settings.insert_one({"key": "demo_seeded", "value": True, "at": now()})
