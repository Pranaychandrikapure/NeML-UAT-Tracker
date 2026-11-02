"""Shared fixtures: Clerk dev test-admin JWT + demo act-as helpers (secret loaded, never printed)."""
import json
import os
import urllib.parse
import urllib.request

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = BASE_URL + "/api"
EMAIL = "crems-test-admin+clerk_test@example.com"


def _bapi(path, body=None, method="POST"):
    req = urllib.request.Request("https://api.clerk.com/v1" + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers={"Authorization": "Bearer " + os.environ["CLERK_SECRET_KEY"],
                                                         "Content-Type": "application/json", "User-Agent": "emergent-test"})
    return json.load(urllib.request.urlopen(req))


@pytest.fixture(scope="session")
def mdb():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="session")
def token():
    users = _bapi(f"/users?email_address={urllib.parse.quote(EMAIL)}", method="GET")
    if not users:
        pytest.skip("Test admin not in Clerk")
    sess = _bapi("/sessions", {"user_id": users[0]["id"]})
    return _bapi(f"/sessions/{sess['id']}/tokens", {"expires_in_seconds": 1800})["jwt"]


@pytest.fixture(scope="session")
def demo(mdb):
    out = {}
    for u in mdb.users.find({"is_demo": True}):
        out[u["name"].split()[0].lower()] = u["id"]
    return out


@pytest.fixture(scope="session")
def call(token, demo):
    def _call(method, path, who=None, **kw):
        h = {"Authorization": f"Bearer {token}"}
        if who:
            h["X-Act-As"] = demo[who]
        return requests.request(method, API + path, headers=h, timeout=60, **kw)
    return _call
