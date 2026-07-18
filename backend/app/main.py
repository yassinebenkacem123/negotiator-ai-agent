"""Entry point: App initialization & routing.

Only responsibility: create the FastAPI app and mount routers. No business
logic here — see app/api/*.py for routes, app/services/*.py for logic.
"""

from fastapi import FastAPI

from app.api import calls, results, search, specs

app = FastAPI(title="The Negotiator — Residential Moving Backend")

app.include_router(specs.router)
app.include_router(search.router)
app.include_router(calls.router)
app.include_router(results.router)


@app.get("/health")
def health():
    return {"status": "ok"}
