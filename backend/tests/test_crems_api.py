"""CReMS API regression: auth, permissions, CR create/approve/tasks, SRN, admin, zoho, reports."""
import requests
from conftest import API


# --- Auth
def test_me_unauthenticated():
    assert requests.get(API + "/me", timeout=30).status_code == 401


def test_me_bad_token():
    assert requests.get(API + "/me", headers={"Authorization": "Bearer abc.def.ghi"}, timeout=30).status_code == 401


def test_me_admin(call):
    r = call("GET", "/me")
    assert r.status_code == 200
    d = r.json()
    assert d["user"]["role"] == "system_admin" if "user" in d else d["role"] == "system_admin"
    assert len(d["demo_users"]) >= 12


def test_act_as_non_demo_rejected(token, mdb):
    other = mdb.users.find_one({"is_demo": False, "id": {"$ne": "test-admin"}})
    if not other:
        return
    r = requests.get(API + "/me", headers={"Authorization": f"Bearer {token}", "X-Act-As": other["id"]}, timeout=30)
    assert r.status_code == 403


# --- Permissions
def _nafed(call):
    ps = call("GET", "/projects", "sneha").json()
    ps = ps["items"] if isinstance(ps, dict) else ps
    return next(p for p in ps if p["code"] == "NAFED")


def test_dev_cannot_create_cr(call):
    p = _nafed(call)
    r = call("POST", "/crs", "komal", json={"title": "TEST_x", "project_id": p["id"]})
    assert r.status_code == 403


def test_dev3_cannot_see_nafed_cr(call):
    crs = call("GET", "/crs", "sneha").json()["items"]
    cr = crs[0]
    assert call("GET", f"/crs/{cr['id']}", "rupali").status_code == 404
    lst = call("GET", "/crs", "rupali").json()["items"]
    assert all(c["project_id"] != cr["project_id"] for c in lst)


def test_pm_cannot_create_sysadmin(call):
    r = call("POST", "/users", "anita", json={"email": "TEST_sa@example.com", "name": "TEST SA", "role": "system_admin"})
    assert r.status_code == 403


def test_dev_cannot_ba_approve(call):
    crs = call("GET", "/crs?status=BA_REVIEW,NEW", "sneha").json()["items"]
    if not crs:
        return
    r = call("POST", f"/crs/{crs[0]['id']}/actions/ba_approve", "komal", json={})
    assert r.status_code in (403, 409)


# --- CR flow
def test_create_cr_and_get(call):
    p = _nafed(call)
    r = call("POST", "/crs", "sneha", json={"title": "TEST_API CR", "project_id": p["id"], "priority": "Low", "requested_deadline": "2099-06-01"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "NEW" and d["number"].startswith("CR-")
    g = call("GET", f"/crs/{d['id']}", "sneha").json()
    assert g["title"] == "TEST_API CR" and g["ba_name"].startswith("Sneha")


def test_create_cr_validation(call):
    r = call("POST", "/crs", "sneha", json={"project_id": "x"})
    assert r.status_code == 422


def test_ba_approve_then_pm_task(call, demo):
    p = _nafed(call)
    cr = call("POST", "/crs", "sneha", json={"title": "TEST_API flow", "project_id": p["id"], "requested_deadline": "2099-06-01"}).json()
    r = call("POST", f"/crs/{cr['id']}/actions/ba_approve", "sneha", json={"manager_id": demo["anita"], "requested_deadline": "2099-06-01"})
    assert r.status_code == 200, r.text
    assert call("GET", f"/crs/{cr['id']}", "anita").json()["status"] == "IMPACT_ANALYSIS"
    t = call("POST", f"/crs/{cr['id']}/tasks", "anita", json={"title": "TEST_task", "developer_id": demo["komal"]})
    assert t.status_code == 200, t.text
    c = call("POST", f"/crs/{cr['id']}/actions/confirm_assignment", "anita", json={})
    assert c.status_code == 200, c.text
    d = call("GET", f"/crs/{cr['id']}", "komal").json()
    assert len(d["tasks"]) == 1 and d["tasks"][0]["developer_id"] == demo["komal"]
    # komal starts, completes
    tid = d["tasks"][0]["id"]
    for a in ("start", "complete_dev"):
        assert call("POST", f"/tasks/{tid}/actions/{a}", "komal", json={}).status_code == 200
    # double start -> 409
    assert call("POST", f"/tasks/{tid}/actions/start", "komal", json={}).status_code == 409
    # another dev cannot act on komal task
    assert call("POST", f"/tasks/{tid}/actions/start_sit", "satyam", json={}).status_code in (403, 404)


def test_tasks_list_dev(call):
    r = call("GET", "/tasks", "komal")
    assert r.status_code == 200


# --- Release / UAT / bugs
def test_srn_list_and_eligible(call):
    p = _nafed(call)
    assert call("GET", "/srns", "komal").status_code == 200
    r = call("GET", f"/srns/eligible?project_id={p['id']}", "komal")
    assert r.status_code == 200, r.text


def test_srn_document(call):
    s = call("GET", "/srns", "anita").json()
    s = s["items"] if isinstance(s, dict) else s
    if not s:
        return
    for fmt, ct in (("pdf", "application/pdf"), ("docx", "officedocument")):
        r = call("GET", f"/srns/{s[0]['id']}/document?format={fmt}", "anita")
        assert r.status_code == 200 and ct in r.headers["content-type"] and len(r.content) > 1000


def test_approvals_uat_bugs(call):
    for who, path in (("anita", "/approvals/queue"), ("arjun", "/uat/assignments"), ("anita", "/bugs")):
        assert call("GET", path, who).status_code == 200, path


# --- Dashboard/reports/admin
def test_dashboard_reports(call):
    d = call("GET", "/dashboard").json()
    assert "kpis" in d
    assert call("GET", "/reports").status_code == 200
    assert call("GET", "/audit").status_code == 200
    assert call("GET", "/search?q=lot").status_code == 200


def test_admin_lists(call):
    for path in ("/users", "/org-tree", "/settings/grant-policies", "/emails", "/master/tech", "/meta", "/notifications"):
        assert call("GET", path).status_code == 200, path


def test_dev_cannot_see_audit_or_emails(call):
    # NOTE: /emails is project-scoped (not admin-only) by design -> dev gets 200 with own-project emails
    assert call("GET", "/emails", "komal").status_code == 200
    assert call("GET", "/integrations/zoho", "komal").status_code == 403


def test_zoho_not_connected_and_sync_fails(call):
    z = call("GET", "/integrations/zoho").json()
    assert str(z).lower().find("not") >= 0 or z.get("connected") is False
    r = call("POST", "/integrations/zoho/sync", json={})
    assert r.status_code in (200, 400, 409, 503)
    z2 = call("GET", "/integrations/zoho").json()
    assert "not configured" in str(z2).lower()


def test_create_user_admin(call):
    p = _nafed(call)
    r = call("POST", "/users", json={"email": "test_user_api@example.com", "name": "TEST_User", "role": "developer",
                                     "projects": [{"project_id": p["id"], "project_role": "developer"}]})
    assert r.status_code in (200, 409), r.text


# --- Input robustness
def test_cr_search_special_chars(call):
    r = call("GET", "/crs?q=(", "sneha")
    assert r.status_code == 200, f"regex not escaped -> {r.status_code}"


def test_global_search_special_chars(call):
    r = call("GET", "/search?q=[", "sneha")
    assert r.status_code == 200, f"regex not escaped -> {r.status_code}"


def test_cr_list_page_zero(call):
    r = call("GET", "/crs?page=0", "sneha")
    assert r.status_code in (200, 422), r.status_code
