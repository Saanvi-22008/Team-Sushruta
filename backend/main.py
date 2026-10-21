import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.apollo_routes import router as apollo_router
from backend.routes import router, simulator_loop


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(simulator_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
app = FastAPI(
    title="Sushruta API",
    description="Simulated wound readings, deterministic safety status, and Apollo guidance backed by TinyFish.",
    version="0.2.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api")
app.include_router(apollo_router, prefix="/api")
