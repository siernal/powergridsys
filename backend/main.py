"""
main.py — точка входа FastAPI приложения.
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from core.config import get_settings
from core.database import init_db, SessionLocal
from routers import (
    auth_router, assets_router, inspections_router,
    repairs_router, failures_router, risk_router,
    maintenance_router, twin_router, analytics_router,
    simulation_router, ws_router,
)
from services.digital_twin import get_twin
from services.ml_predictor import train_model
from services.transformer_simulator import create_simulator
from sqlalchemy.orm import joinedload

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация при старте: БД, ML модель, Digital Twin."""
    logger.info("🚀 Запуск PowerGrid Maintenance System")

    # 1. Создать таблицы
    init_db()

    # 2. Обучить модель, если её нет
    if not os.path.exists(settings.ml_model_path):
        logger.info("🤖 Обучение ML-модели (первый запуск)...")
        os.makedirs(os.path.dirname(settings.ml_model_path), exist_ok=True)
        train_model(settings.ml_model_path)

    # 3. Построить граф Digital Twin
    db = SessionLocal()
    try:
        from models import Asset, FailureEvent, Repair, SensorSnapshot
        from services.digital_twin import get_twin, asset_age
        from services.maintenance_planner import days_since_last_maintenance
        from sqlalchemy import func, desc

        assets = db.query(Asset).options(joinedload(Asset.asset_type)).all()
        if assets:
            twin = get_twin()
            twin.build_from_assets(assets)
            for asset in assets:
                fc = db.query(func.count(FailureEvent.id)).filter(FailureEvent.asset_id == asset.id).scalar() or 0
                rc = db.query(func.count(Repair.id)).filter(Repair.asset_id == asset.id).scalar() or 0
                dsm = days_since_last_maintenance(asset)
                ls = db.query(SensorSnapshot).filter(SensorSnapshot.asset_id == asset.id).order_by(desc(SensorSnapshot.recorded_at)).first()
                twin.update_node_state(
                    asset.id, fc, rc, dsm,
                    load_percent=ls.load_percent if ls else 65.0,
                    temperature=ls.temperature_c if ls else 10.0,
                )
            logger.info(f"🔗 Digital Twin построен: {twin.graph.number_of_nodes()} узлов")
    finally:
        db.close()

    # 4. Запустить симулятор
    sim = create_simulator(
        db_factory=SessionLocal,
        twin_getter=get_twin,
        tick_interval_sec=30.0,   # тик каждые 30 реальных секунд
        sim_speed=1.0,            # = 1 симулированный час за тик
    )
    await sim.start()
    logger.info("⚡ Симулятор трансформаторов запущен")

    yield

    # Останавливаем симулятор при завершении
    await sim.stop()
    logger.info("👋 Завершение работы")


app = FastAPI(
    title="PowerGrid Maintenance System",
    description="Система учёта и прогнозирования отказов электросетей — ВКР MVP",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS. По умолчанию открыто для локальной разработки и (через "*") для демо.
# На проде можно сузить до домена фронтенда переменной окружения
# CORS_ORIGINS="https://powergrid-frontend.onrender.com" (через запятую — несколько).
_origins_env = os.getenv("CORS_ORIGINS", "")
allow_origins = [o.strip() for o in _origins_env.split(",") if o.strip()] or [
    "http://localhost:5173",
    "http://localhost:3000",
    "*",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Статические файлы (загруженные изображения объектов и пр.).
# Создаём директорию, если её нет, чтобы StaticFiles не падал.
os.makedirs("static/assets", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Регистрация роутеров
app.include_router(auth_router)
app.include_router(assets_router)
app.include_router(inspections_router)
app.include_router(repairs_router)
app.include_router(failures_router)
app.include_router(risk_router)
app.include_router(maintenance_router)
app.include_router(twin_router)
app.include_router(analytics_router)
app.include_router(simulation_router)
app.include_router(ws_router)


@app.get("/")
def root():
    return {
        "app": settings.app_name,
        "version": "1.0.0",
        "docs": "/docs",
        "status": "running",
    }


@app.get("/health")
def health():
    return {"status": "ok"}
