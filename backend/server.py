import asyncio
import logging
import os

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from core import client
from clerk_auth import clerk_router
import routes_org
import routes_cr
import routes_release
import routes_uat
import routes_dash
import zoho
from seed import seed
from emailer import worker_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
app = FastAPI(title="CReMS API")

for r in (routes_org.router, routes_cr.router, routes_release.router, routes_uat.router, routes_dash.router, zoho.router):
    app.include_router(r)
app.include_router(clerk_router)


@app.get("/api/health")
async def health():
    return {"ok": True}


app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    await seed()
    app.state.worker = asyncio.create_task(worker_loop())


@app.on_event("shutdown")
async def shutdown():
    client.close()
