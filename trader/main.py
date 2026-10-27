"""Application entry point: `uv run uvicorn trader.main:app`."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import gw2_syncer, router
from .db import ROOT, tx
from .engine import engine
from .seed import seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(_app):
    with tx() as c:
        if seed(c):
            logging.getLogger("trader").info("fresh world seeded; fast-forwarding market history")
        engine.load(c)
    engine.start()
    gw2_syncer.start()
    yield
    gw2_syncer.stopped.set()
    gw2_syncer.wake.set()
    engine.stop()


app = FastAPI(title="Біржа хламу", lifespan=lifespan)
app.include_router(router)
app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
