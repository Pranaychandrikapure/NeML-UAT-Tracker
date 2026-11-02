"""End-to-end workflow smoke test using a Clerk dev test admin + demo act-as."""
import json
import os
import sys
import urllib.request
import urllib.parse

import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
SK = os.environ["CLERK_SECRET_KEY"]
API = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0] + "/api"
EMAIL = "crems-test-admin+clerk_test@example.com"
mdb = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def bapi(path, body=None, method="POST"):
    req = urllib.request.Request("https://api.clerk.com/v1" + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Authorization": "Bearer " + SK, "Content-Type": "application/json", "User-Agent": "emergent-test"})
    return json.load(urllib.request.urlopen(req))


existing = bapi(f"/users?email_address={urllib.parse.quote(EMAIL)}", method="GET")
user = existing[0] if existing else bapi("/users", {"email_address": [EMAIL], "password": "Test-pass-12345!", "skip_password_checks": True})
if not mdb.users.find_one({"email": EMAIL}):
    mdb.users.insert_one({"id": "test-admin", "email": EMAIL, "name": "TEST Admin", "role": "system_admin", "active": True, "is_demo": False, "is_test": True, "reporting_manager_id": None})
session = bapi("/sessions", {"user_id": user["id"]})


def tok():
    return bapi(f"/sessions/{session['id']}/tokens", {"expires_in_seconds": 600})["jwt"]


T = tok()
demo = {u["role"] + ("" if u["role"] != "developer" else ":" + u["name"].split()[0]): u["id"] for u in mdb.users.find({"is_demo": True})}


def call(method, path, who=None, body=None, expect=200):
    h = {"Authorization": f"Bearer {T}"}
    if who:
        h["X-Act-As"] = demo[who]
    r = requests.request(method, API + path, headers=h, json=body, timeout=60)
    ok = r.status_code == expect
    print(("PASS" if ok else "FAIL"), method, path, who or "admin", r.status_code, "" if ok else r.text[:300])
    if not ok and expect == 200:
        sys.exit(1)
    return r.json() if r.headers.get("content-type", "").startswith("application/json") else r.content


call("GET", "/me")
crs = call("GET", "/crs", "ba", None)["items"]
cr = next(c for c in crs if c["number"].endswith("0001"))
ready = next(c for c in crs if c["number"].endswith("0004"))
call("POST", "/crs", "developer:Komal", {"title": "x", "project_id": cr["project_id"]}, expect=403)
call("POST", f"/crs/{cr['id']}/actions/ba_approve", "ba", {"manager_id": demo["pm"], "requested_deadline": cr["requested_deadline"]})
call("POST", f"/crs/{cr['id']}/tasks", "pm", {"title": "Threshold API", "developer_id": demo["developer:Komal"]})
call("POST", f"/crs/{cr['id']}/tasks", "pm", {"title": "Self-assigned UI", "developer_id": demo["pm"]})
call("POST", f"/crs/{cr['id']}/deadline-requests", "pm", {"proposed_deadline": "2099-01-01", "reason": "More effort"})
dl = call("GET", f"/crs/{cr['id']}", "ba")["deadline_requests"][0]
call("POST", f"/deadline-requests/{dl['id']}/decide", "ba", {"decision": "APPROVE"})
call("POST", f"/crs/{cr['id']}/actions/confirm_assignment", "pm", {})
d = call("GET", f"/crs/{cr['id']}", "pm")
assert d["approved_deadline"] == "2099-01-01" and d["requested_deadline"] == cr["requested_deadline"], "deadline history"
for t in d["tasks"]:
    who = "developer:Komal" if t["developer_id"] == demo["developer:Komal"] else "pm"
    for a in ("start", "complete_dev", "start_sit"):
        call("POST", f"/tasks/{t['id']}/actions/{a}", who, {})
    st = call("GET", f"/crs/{cr['id']}", "pm")["status"]
    print("CR status after", t["number"], "->", st)
    call("POST", f"/tasks/{t['id']}/actions/sit_result", who, {"result": "PASS", "evidence": "TEST evidence"})
assert call("GET", f"/crs/{cr['id']}", "pm")["status"] == "READY_FOR_UAT"
srn = call("POST", "/srns", "developer:Komal", {"project_id": cr["project_id"], "release_version": "TEST-V1", "summary": "TEST release", "items": [{"cr_id": cr["id"]}, {"cr_id": ready["id"]}]})
call("POST", f"/srns/{srn['id']}/submit", "developer:Komal")
call("POST", f"/srns/{srn['id']}/decision", "developer:Komal", {"decision": "APPROVE"}, expect=403)
call("POST", f"/srns/{srn['id']}/decision", "pm", {"decision": "APPROVE"}, expect=403)  # PM self-assigned a task -> SoD
cfg = call("GET", f"/projects/{cr['project_id']}", "pm")["config"]
cfg["allow_self_approval"] = True
call("PUT", f"/projects/{cr['project_id']}/config", "pm", cfg)
call("POST", f"/srns/{srn['id']}/decision", "pm", {"decision": "APPROVE"})
call("POST", f"/srns/{srn['id']}/decision", "team_lead", {"decision": "APPROVE"})
call("POST", f"/srns/{srn['id']}/decision", "ba", {"decision": "APPROVE"})
call("POST", f"/srns/{srn['id']}/decision", "uat_lead", {"decision": "APPROVE"})
assert call("GET", f"/srns/{srn['id']}", "pm")["status"] == "APPROVED"
dep = call("POST", f"/srns/{srn['id']}/deployments", "pm", {})
call("POST", f"/deployments/{dep['id']}/start", "pm")
call("POST", f"/deployments/{dep['id']}/confirm", "pm", {"success": True, "build_id": "b1"})
assert call("GET", f"/crs/{cr['id']}", "pm")["status"] == "UAT_DEPLOYED"
call("GET", f"/srns/{srn['id']}/document?format=pdf", "pm")
call("GET", f"/srns/{srn['id']}/document?format=docx", "pm")
ua = [a for a in call("GET", "/uat/assignments", "uat_member") if a["cr_id"] == cr["id"]][0]
call("POST", f"/uat/assignments/{ua['id']}/action/start", "uat_member", {})
call("POST", f"/uat/assignments/{ua['id']}/action/add_case", "uat_member", {"title": "TEST threshold", "result": "FAIL"})
bug = call("POST", "/bugs", "uat_member", {"cr_id": cr["id"], "uat_assignment_id": ua["id"], "title": "TEST bug", "severity": "High"})
call("POST", f"/uat/assignments/{ua['id']}/action/fail", "uat_member", {"comment": "bug found"})
call("POST", f"/crs/{cr['id']}/actions/close", "ba", {}, expect=409)
call("POST", f"/bugs/{bug['id']}/action/assign", "pm", {"developer_id": demo["developer:Komal"]})
for a, b in [("start", {}), ("fixed", {"fix_notes": "fixed"}), ("start_sit", {}), ("sit_pass", {"evidence": "ok"})]:
    call("POST", f"/bugs/{bug['id']}/action/{a}", "developer:Komal", b)
s2 = call("POST", "/srns", "developer:Komal", {"project_id": cr["project_id"], "release_version": "TEST-V2", "summary": "TEST bugfix", "bug_ids": [bug["id"]]})
call("POST", f"/srns/{s2['id']}/submit", "developer:Komal")
for who in ("pm", "team_lead", "ba", "uat_lead"):
    call("POST", f"/srns/{s2['id']}/decision", who, {"decision": "APPROVE"})
dep2 = call("POST", f"/srns/{s2['id']}/deployments", "pm", {})
call("POST", f"/deployments/{dep2['id']}/start", "pm")
call("POST", f"/deployments/{dep2['id']}/confirm", "pm", {"success": True})
ua = call("GET", "/uat/assignments", "uat_member")
ua = [a for a in ua if a["cr_id"] == cr["id"] and a["status"] == "RETEST_PENDING"][0]
call("POST", f"/uat/assignments/{ua['id']}/action/start", "uat_member", {})
call("POST", f"/bugs/{bug['id']}/action/verify", "uat_member", {})
call("POST", f"/uat/assignments/{ua['id']}/action/pass", "uat_member", {"comment": "ok"})
print("CR status", call("GET", f"/crs/{cr['id']}", "ba")["status"])
call("POST", f"/crs/{cr['id']}/actions/close", "ba", {})
print("dashboard", call("GET", "/dashboard", "ba")["kpis"])
cfg["allow_self_approval"] = False
call("PUT", f"/projects/{cr['project_id']}/config", "pm", cfg)
print("emails", [(m["status"], m["last_error"]) for m in mdb.email_messages.find({}, {"_id": 0})])
