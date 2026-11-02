from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr

from core import (db, now, uid, err, audit, notify, current_user, is_admin, my_project_ids, pscope, require_project,
                  get_setting, users_map, ROLES, DEFAULT_GRANTS, DEFAULT_TECH, DEFAULT_PROJECT_CONFIG, MANAGERS, DEMO_MODE)

router = APIRouter(prefix="/api")


class Membership(BaseModel):
    project_id: str
    project_role: Optional[str] = None


class UserIn(BaseModel):
    name: str
    email: EmailStr
    role: str
    reporting_manager_id: Optional[str] = None
    department: str = ""
    active: bool = True
    notify_email: bool = True
    projects: List[Membership] = []
    can_create_developers: bool = False
    can_create_projects: bool = False


class UserPatch(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    reporting_manager_id: Optional[str] = None
    department: Optional[str] = None
    active: Optional[bool] = None
    notify_email: Optional[bool] = None
    projects: Optional[List[Membership]] = None
    can_create_developers: Optional[bool] = None
    can_create_projects: Optional[bool] = None


class ProjectIn(BaseModel):
    name: str
    code: str
    description: str = ""
    owner_name: str = ""
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: str = "Active"
    tech_stack: List[str] = []


class ProjectPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    owner_name: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: Optional[str] = None
    tech_stack: Optional[List[str]] = None


class MemberIn(BaseModel):
    user_id: str
    project_role: Optional[str] = None


class NamedIn(BaseModel):
    name: str
    description: str = ""


class NamedPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    archived: Optional[bool] = None
    status: Optional[str] = None


async def grantable(u):
    pol = await get_setting("grant_policies", DEFAULT_GRANTS)
    roles = list(pol.get(u["role"], []))
    if u["role"] == "team_lead" and u.get("can_create_developers") and "developer" not in roles:
        roles.append("developer")
    return roles


async def subtree_ids(root_id):
    ids, frontier = set(), [root_id]
    while frontier:
        kids = await db.users.distinct("id", {"reporting_manager_id": {"$in": frontier}})
        frontier = [k for k in kids if k not in ids]
        ids.update(frontier)
    return ids


async def managed_project_ids(u):
    if is_admin(u):
        return None
    return await db.project_members.distinct("project_id", {"user_id": u["id"], "project_role": {"$in": list(MANAGERS | {"ba_lead", "uat_lead", "uat_manager"})}})


async def _apply_memberships(u, user_id, role, memberships):
    allowed = await managed_project_ids(u)
    for m in memberships:
        if allowed is not None and m.project_id not in allowed:
            err(403, "You cannot assign a project you do not manage")
        if not await db.projects.find_one({"id": m.project_id}):
            err(400, "Unknown project")
    current = await db.project_members.find({"user_id": user_id}, {"_id": 0}).to_list(200)
    keep = {m.project_id for m in memberships}
    for c in current:
        if c["project_id"] not in keep and (allowed is None or c["project_id"] in allowed):
            await db.project_members.delete_one({"user_id": user_id, "project_id": c["project_id"]})
    for m in memberships:
        pr = m.project_role or role
        if pr not in ROLES or pr == "system_admin":
            err(400, "Invalid project role")
        await db.project_members.update_one({"user_id": user_id, "project_id": m.project_id},
                                            {"$set": {"project_role": pr, "added_by": u["id"], "at": now()}}, upsert=True)


@router.get("/me")
async def me(u=Depends(current_user)):
    ms = await db.project_members.find({"user_id": u["id"]}, {"_id": 0}).to_list(200)
    pids = None if is_admin(u) else [m["project_id"] for m in ms]
    projects = await db.projects.find(pscope(pids, "id"), {"_id": 0, "id": 1, "name": 1, "code": 1}).sort("name", 1).to_list(500)
    out = {**u, "memberships": ms, "projects": projects, "grantable_roles": await grantable(u),
           "role_label": ROLES[u["role"]]["label"], "demo_mode": DEMO_MODE,
           "can_create_projects": is_admin(u) or u["role"] == "senior_pm" or (u["role"] == "project_lead" and u.get("can_create_projects"))}
    real = await db.users.find_one({"id": u.get("real_user_id") or u["id"]}, {"_id": 0})
    if DEMO_MODE and real and real["role"] == "system_admin":
        out["demo_users"] = await db.users.find({"is_demo": True, "active": True}, {"_id": 0, "id": 1, "name": 1, "role": 1}).sort("role", 1).to_list(100)
    return out


class PrefIn(BaseModel):
    notify_email: bool


@router.patch("/me/preferences")
async def my_prefs(body: PrefIn, u=Depends(current_user)):
    if u.get("real_user_id"):
        err(403, "Preferences cannot be changed while acting as another user")
    await db.users.update_one({"id": u["id"]}, {"$set": {"notify_email": body.notify_email}})
    return {"ok": True}


@router.get("/meta")
async def meta(u=Depends(current_user)):
    techs = await db.tech_options.find({}, {"_id": 0}).sort("name", 1).to_list(200)
    return {"roles": [{"key": k, **v} for k, v in ROLES.items()], "tech_options": [t["name"] for t in techs]}


@router.get("/users")
async def list_users(u=Depends(current_user), q: str = "", role: str = "", project_id: str = ""):
    f = {}
    if not is_admin(u):
        pids = await my_project_ids(u)
        colleague_ids = await db.project_members.distinct("user_id", {"project_id": {"$in": pids}})
        f["id"] = {"$in": list(set(colleague_ids) | await subtree_ids(u["id"]) | {u["id"]})}
    if q:
        f["$or"] = [{"name": {"$regex": q, "$options": "i"}}, {"email": {"$regex": q, "$options": "i"}}]
    if role:
        f["role"] = role
    if project_id:
        f.setdefault("$and", []).append({"id": {"$in": await db.project_members.distinct("user_id", {"project_id": project_id})}})
    users = await db.users.find(f, {"_id": 0, "clerk_id": 0}).sort("name", 1).to_list(2000)
    sub = None if is_admin(u) else await subtree_ids(u["id"])
    mem = await db.project_members.find({"user_id": {"$in": [x["id"] for x in users]}}, {"_id": 0}).to_list(5000)
    for x in users:
        x["memberships"] = [m for m in mem if m["user_id"] == x["id"]]
        x["can_manage"] = sub is None or x["id"] in sub
    return users


@router.post("/users")
async def create_user(body: UserIn, u=Depends(current_user)):
    if body.role not in await grantable(u):
        err(403, "You are not permitted to grant this role")
    email = body.email.lower()
    domains = await get_setting("allowed_domains", [])
    if domains and email.split("@")[1] not in domains:
        err(400, "Email domain is not organization-approved")
    if await db.users.find_one({"email": email}):
        err(409, "A user with this email already exists")
    mgr_id = body.reporting_manager_id or u["id"]
    if not is_admin(u) and mgr_id != u["id"] and mgr_id not in await subtree_ids(u["id"]):
        err(403, "Reporting manager must be within your hierarchy")
    if not body.projects and body.role not in ("system_admin", "project_lead", "ba_lead", "uat_lead"):
        err(400, "Assign at least one project")
    doc = {**body.model_dump(exclude={"projects"}), "email": email, "id": uid(), "reporting_manager_id": mgr_id,
           "is_demo": False, "created_by": u["id"], "created_at": now()}
    if not is_admin(u):
        doc["can_create_projects"] = False
    await db.users.insert_one(dict(doc))
    await _apply_memberships(u, doc["id"], body.role, body.projects)
    await audit(u, "USER_CREATED", "user", doc["id"], None, None, {"email": email, "role": body.role, "projects": [p.project_id for p in body.projects]})
    doc.pop("_id", None)
    return doc


@router.patch("/users/{user_id}")
async def update_user(user_id: str, body: UserPatch, u=Depends(current_user)):
    t = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not t:
        err(404, "User not found")
    if user_id == u["id"] and not is_admin(u):
        err(403, "You cannot change your own access")
    if not is_admin(u) and user_id not in await subtree_ids(u["id"]):
        err(403, "User is outside your hierarchy")
    grants = await grantable(u)
    if not is_admin(u) and t["role"] not in grants:
        err(403, "You cannot manage this role")
    if body.role and body.role != t["role"] and body.role not in grants:
        err(403, "You are not permitted to grant this role")
    sets = body.model_dump(exclude_none=True, exclude={"projects"})
    if not is_admin(u):
        sets.pop("can_create_projects", None)
    if sets:
        await db.users.update_one({"id": user_id}, {"$set": {**sets, "updated_at": now()}})
        await audit(u, "USER_UPDATED", "user", user_id, None, {k: t.get(k) for k in sets}, sets)
    if body.projects is not None:
        await _apply_memberships(u, user_id, body.role or t["role"], body.projects)
        await audit(u, "PROJECT_ASSIGNMENT", "user", user_id, None, None, {"projects": [p.model_dump() for p in body.projects]})
    return await db.users.find_one({"id": user_id}, {"_id": 0, "clerk_id": 0})


@router.get("/org-tree")
async def org_tree(u=Depends(current_user)):
    users = await list_users(u)
    ids = {x["id"] for x in users}
    nodes = {x["id"]: {"id": x["id"], "name": x["name"], "role": x["role"], "role_label": ROLES[x["role"]]["label"],
                       "active": x.get("active", True), "email": x["email"], "children": []} for x in users}
    roots = []
    for x in users:
        p = x.get("reporting_manager_id")
        (nodes[p]["children"] if p in ids else roots).append(nodes[x["id"]])
    return roots


@router.get("/settings/grant-policies")
async def get_grants(u=Depends(current_user)):
    return {"policies": await get_setting("grant_policies", DEFAULT_GRANTS), "allowed_domains": await get_setting("allowed_domains", [])}


class GrantsIn(BaseModel):
    policies: dict
    allowed_domains: List[str] = []


@router.put("/settings/grant-policies")
async def put_grants(body: GrantsIn, u=Depends(current_user)):
    if not is_admin(u):
        err(403, "Admin only")
    for k, v in body.policies.items():
        if k not in ROLES or any(r not in ROLES for r in v):
            err(400, "Unknown role in policy")
    body.policies["system_admin"] = list(ROLES.keys())
    await db.settings.update_one({"key": "grant_policies"}, {"$set": {"value": body.policies}}, upsert=True)
    await db.settings.update_one({"key": "allowed_domains"}, {"$set": {"value": [d.lower() for d in body.allowed_domains]}}, upsert=True)
    await audit(u, "GRANT_POLICY_UPDATED", "settings", "grant_policies", None, None, body.model_dump())
    return {"ok": True}


@router.get("/master/tech")
async def list_tech(u=Depends(current_user)):
    return [t["name"] for t in await db.tech_options.find({}, {"_id": 0}).sort("name", 1).to_list(200)]


@router.post("/master/tech")
async def add_tech(body: NamedIn, u=Depends(current_user)):
    if not is_admin(u):
        err(403, "Admin only")
    await db.tech_options.update_one({"name": body.name}, {"$set": {"name": body.name}}, upsert=True)
    return {"ok": True}


# ---------- Projects ----------
@router.get("/projects")
async def list_projects(u=Depends(current_user), q: str = ""):
    f = pscope(await my_project_ids(u), "id")
    if q:
        f["name"] = {"$regex": q, "$options": "i"}
    ps = await db.projects.find(f, {"_id": 0, "raw": 0}).sort("name", 1).to_list(500)
    for p in ps:
        p["member_count"] = await db.project_members.count_documents({"project_id": p["id"]})
        p["open_crs"] = await db.change_requests.count_documents({"project_id": p["id"], "status": {"$nin": ["CLOSED", "CANCELLED"]}})
        p["open_bugs"] = await db.bugs.count_documents({"project_id": p["id"], "status": {"$nin": ["VERIFIED", "CLOSED"]}})
        p["module_count"] = await db.modules.count_documents({"project_id": p["id"], "archived": {"$ne": True}})
    return ps


@router.post("/projects")
async def create_project(body: ProjectIn, u=Depends(current_user)):
    if not (is_admin(u) or u["role"] == "senior_pm" or (u["role"] == "project_lead" and u.get("can_create_projects"))):
        err(403, "You are not permitted to create projects")
    if await db.projects.find_one({"code": body.code}):
        err(409, "Project code already exists")
    p = {**body.model_dump(), "id": uid(), "zoho_id": None, "source": "MANUAL", "config": DEFAULT_PROJECT_CONFIG,
         "created_by": u["id"], "created_at": now(), "updated_at": now()}
    await db.projects.insert_one(dict(p))
    if not is_admin(u):
        await db.project_members.insert_one({"project_id": p["id"], "user_id": u["id"], "project_role": u["role"], "at": now()})
    await audit(u, "PROJECT_CREATED", "project", p["id"], p["id"], None, {"name": body.name})
    p.pop("_id", None)
    return p


@router.get("/projects/{pid}")
async def get_project(pid: str, u=Depends(current_user)):
    pr = await require_project(u, pid)
    p = await db.projects.find_one({"id": pid}, {"_id": 0, "raw": 0})
    if not p:
        err(404, "Project not found")
    ms = await db.project_members.find({"project_id": pid}, {"_id": 0}).to_list(500)
    um = await users_map([m["user_id"] for m in ms])
    p["members"] = [{**m, **um.get(m["user_id"], {})} for m in ms]
    mods = await db.modules.find({"project_id": pid}, {"_id": 0}).sort("name", 1).to_list(500)
    for m in mods:
        m["screens"] = await db.screens.find({"module_id": m["id"]}, {"_id": 0}).sort("name", 1).to_list(500)
        m["cr_count"] = await db.change_requests.count_documents({"impacted_module_ids": m["id"]})
        m["open_bugs"] = await db.bugs.count_documents({"module_id": m["id"], "status": {"$nin": ["VERIFIED", "CLOSED"]}})
        m["developers"] = [um2["name"] for um2 in (await users_map(await db.cr_tasks.distinct("developer_id", {"module_id": m["id"]}))).values()]
    p["modules"] = mods
    p["my_project_role"] = pr
    return p


async def _require_manage_project(u, pid):
    pr = await require_project(u, pid)
    if not (is_admin(u) or pr in ("project_lead", "senior_pm", "pm")):
        err(403, "Only project management can change project settings")
    return pr


@router.patch("/projects/{pid}")
async def patch_project(pid: str, body: ProjectPatch, u=Depends(current_user)):
    await _require_manage_project(u, pid)
    sets = body.model_dump(exclude_none=True)
    await db.projects.update_one({"id": pid}, {"$set": {**sets, "updated_at": now()}})
    await audit(u, "PROJECT_UPDATED", "project", pid, pid, None, sets)
    return await db.projects.find_one({"id": pid}, {"_id": 0, "raw": 0})


@router.put("/projects/{pid}/config")
async def put_config(pid: str, body: dict, u=Depends(current_user)):
    await _require_manage_project(u, pid)
    cfg = {**DEFAULT_PROJECT_CONFIG, **{k: v for k, v in body.items() if k in DEFAULT_PROJECT_CONFIG}}
    for st in cfg["approval_stages"]:
        if not st.get("roles") or any(r not in ROLES for r in st["roles"]):
            err(400, "Invalid approval stage roles")
    await db.projects.update_one({"id": pid}, {"$set": {"config": cfg}})
    await audit(u, "PROJECT_CONFIG_UPDATED", "project", pid, pid, None, cfg)
    return cfg


@router.post("/projects/{pid}/members")
async def add_member(pid: str, body: MemberIn, u=Depends(current_user)):
    await _require_manage_project(u, pid)
    t = await db.users.find_one({"id": body.user_id}, {"_id": 0})
    if not t:
        err(404, "User not found")
    pr = body.project_role or t["role"]
    if pr not in ROLES or pr == "system_admin":
        err(400, "Invalid project role")
    await db.project_members.update_one({"project_id": pid, "user_id": body.user_id}, {"$set": {"project_role": pr, "added_by": u["id"], "at": now()}}, upsert=True)
    await audit(u, "PROJECT_ASSIGNMENT", "project", pid, pid, None, {"user_id": body.user_id, "project_role": pr})
    await notify([body.user_id], "PROJECT_ASSIGNED", "You were added to a project", f"/projects/{pid}")
    return {"ok": True}


@router.delete("/projects/{pid}/members/{user_id}")
async def remove_member(pid: str, user_id: str, u=Depends(current_user)):
    await _require_manage_project(u, pid)
    await db.project_members.delete_one({"project_id": pid, "user_id": user_id})
    await audit(u, "PROJECT_UNASSIGNED", "project", pid, pid, {"user_id": user_id}, None)
    return {"ok": True}


@router.post("/projects/{pid}/modules")
async def add_module(pid: str, body: NamedIn, u=Depends(current_user)):
    pr = await require_project(u, pid)
    if not (is_admin(u) or pr in MANAGERS or pr == "developer"):
        err(403, "Not permitted to add modules")
    if await db.modules.find_one({"project_id": pid, "name": {"$regex": f"^{body.name.strip()}$", "$options": "i"}}):
        err(409, "Module name already exists in this project")
    proj = await db.projects.find_one({"id": pid}, {"_id": 0, "config": 1})
    needs = (proj.get("config") or {}).get("require_module_approval", True) and pr in ("team_lead", "developer")
    m = {"id": uid(), "project_id": pid, "name": body.name.strip(), "description": body.description, "archived": False,
         "status": "PROPOSED" if needs else "ACTIVE", "created_by": u["id"], "created_at": now()}
    await db.modules.insert_one(dict(m))
    await audit(u, "MODULE_CREATED", "module", m["id"], pid, None, {"name": m["name"], "status": m["status"]})
    m.pop("_id", None)
    return m


@router.patch("/modules/{mid}")
async def patch_module(mid: str, body: NamedPatch, u=Depends(current_user)):
    m = await db.modules.find_one({"id": mid}, {"_id": 0})
    if not m:
        err(404, "Not found")
    pr = await require_project(u, m["project_id"])
    if not (is_admin(u) or pr in ("project_lead", "senior_pm", "pm")):
        err(403, "Only PM and above can edit, approve or archive modules")
    sets = body.model_dump(exclude_none=True)
    await db.modules.update_one({"id": mid}, {"$set": sets})
    await audit(u, "MODULE_UPDATED", "module", mid, m["project_id"], {k: m.get(k) for k in sets}, sets)
    return {**m, **sets}


@router.post("/modules/{mid}/screens")
async def add_screen(mid: str, body: NamedIn, u=Depends(current_user)):
    m = await db.modules.find_one({"id": mid}, {"_id": 0})
    if not m:
        err(404, "Not found")
    pr = await require_project(u, m["project_id"])
    if not (is_admin(u) or pr in MANAGERS or pr == "developer"):
        err(403, "Not permitted")
    if await db.screens.find_one({"module_id": mid, "name": {"$regex": f"^{body.name.strip()}$", "$options": "i"}}):
        err(409, "Screen name already exists in this module")
    s = {"id": uid(), "module_id": mid, "project_id": m["project_id"], "name": body.name.strip(), "description": body.description,
         "archived": False, "status": "PROPOSED" if pr in ("team_lead", "developer") else "ACTIVE", "created_by": u["id"], "created_at": now()}
    await db.screens.insert_one(dict(s))
    await audit(u, "SCREEN_CREATED", "screen", s["id"], m["project_id"], None, {"name": s["name"]})
    s.pop("_id", None)
    return s


@router.patch("/screens/{sid}")
async def patch_screen(sid: str, body: NamedPatch, u=Depends(current_user)):
    s = await db.screens.find_one({"id": sid}, {"_id": 0})
    if not s:
        err(404, "Not found")
    pr = await require_project(u, s["project_id"])
    if not (is_admin(u) or pr in ("project_lead", "senior_pm", "pm")):
        err(403, "Only PM and above can edit screens")
    sets = body.model_dump(exclude_none=True)
    await db.screens.update_one({"id": sid}, {"$set": sets})
    await audit(u, "SCREEN_UPDATED", "screen", sid, s["project_id"], None, sets)
    return {**s, **sets}
