"""Entry point: App initialization & routing.

Only responsibility: create the FastAPI app and mount routers. No business
logic here — see app/api/*.py for routes, app/services/*.py for logic.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import calls, results, search, specs

app = FastAPI(title="The Negotiator — Residential Moving Backend")

# Dev-friendly wildcard: the frontend runs on a different port during local
# testing. Tighten this to a specific origin before any real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(specs.router)
app.include_router(search.router)
app.include_router(calls.router)
app.include_router(results.router)


@app.get("/health")
def health():
    return {"status": "healthy"}
