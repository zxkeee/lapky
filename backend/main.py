"""«Лапки» — спільний сервер для вебкарти й Telegram-бота.

Запуск:  uvicorn backend.main:app --reload
Документація API (Swagger): http://127.0.0.1:8000/docs
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config
from .db import init_db
from .routers import applications, internal, needs, shelters, tasks, users


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Лапки API",
    version="2.0.0",
    description="Єдине джерело даних про притулки України для вебкарти й Telegram-бота.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["X-Total-Count"])

for module in (shelters, needs, tasks, users, applications, internal):
    app.include_router(module.router)

# ---------- вебкарта (статичні файли, монтується останньою) ----------
app.mount("/", StaticFiles(directory=config.WEB_DIR, html=True), name="web")
