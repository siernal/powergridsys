# PowerGrid Maintenance System

> Веб-MVP для дипломной работы (ВКР): «Система учёта обслуживания электрических сетей с модулем прогнозирования отказов и планирования ремонтов на основе цифровой копии электросети».

Полностью автономная демо-система — работает на синтетических данных, без подключения к SCADA или внешним API.
Демо: https://powergrid-frontend-k6hc.onrender.com/

## Стек

| Слой       | Технологии                                                           |
|------------|----------------------------------------------------------------------|
| Frontend   | React 18 + TypeScript + Vite + React Router 6 + Recharts + axios     |
| Backend    | FastAPI + SQLAlchemy 2.0 + Pydantic v2 + JWT (HS256)                 |
| ML         | scikit-learn (Random Forest), pandas, numpy                          |
| Digital Twin | NetworkX (DiGraph)                                                 |
| БД         | PostgreSQL 15                                                        |
| Деплой     | Docker Compose                                                       |

## Быстрый запуск (Docker)

```bash
git clone <repo>
cd vkr
docker compose up --build
```

После сборки откройте:

- Веб-интерфейс — http://localhost:5173
- Swagger UI    — http://localhost:8000/docs
- БД (psql)     — `localhost:5432`, db=`powergrid`, user=`pguser`, pass=`pgpass`

При первом старте бэкенд:

1. создаст таблицы;
2. сгенерирует **120 объектов** с историей осмотров/ремонтов/отказов, погодой и телеметрией;
3. сгенерирует **обучающий датасет (6000 строк)** и обучит Random Forest;
4. построит граф цифровой копии.

Холодный старт занимает ~30 секунд.

## Демо-учётки

| Логин      | Пароль       | Роль       |
|------------|--------------|------------|
| `admin`    | `admin123`   | Администратор |
| `engineer` | `engineer123`| Инженер    |
| `inspector`| `inspect123` | Инспектор  |
| `viewer`   | `viewer123`  | Просмотр   |

## Локальная разработка без Docker

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# поднимите PostgreSQL отдельно или поправьте DATABASE_URL под SQLite:
export DATABASE_URL="postgresql://pguser:pgpass@localhost:5432/powergrid"

python seed/seed_data.py        # один раз — заполнить БД синтетикой
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Откроется на http://localhost:5173, прокси `/api → http://localhost:8000`.

## Структура проекта

```
vkr/
├── backend/
│   ├── main.py                 # FastAPI entry, lifespan (init_db, train, twin)
│   ├── routers.py              # все REST-эндпоинты
│   ├── schemas.py              # Pydantic-модели
│   ├── core/
│   │   ├── config.py           # Settings (env-based)
│   │   ├── database.py         # SQLAlchemy engine, SessionLocal, init_db
│   │   └── security.py         # JWT + bcrypt
│   ├── models/__init__.py      # ORM-классы (User, Asset, Inspection, ...)
│   ├── services/
│   │   ├── digital_twin.py     # NetworkX-граф, health/risk
│   │   ├── ml_predictor.py     # Random Forest + генерация датасета
│   │   └── maintenance_planner.py  # планировщик ТОиР
│   ├── seed/seed_data.py       # синтетический заполнитель БД
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── package.json, vite.config.ts, tsconfig.json
│   ├── index.html, Dockerfile
│   └── src/
│       ├── main.tsx, App.tsx, styles.css
│       ├── api/client.ts       # axios-клиент
│       ├── types.ts            # доменные TS-типы
│       ├── components/         # Layout, RiskBadge, StatCard, Loading
│       └── pages/              # Dashboard, AssetsList, AssetDetail,
│                               # RiskAnalytics, MaintenancePlan, Analytics
├── docs/architecture.md        # подробный design-doc для пояснительной записки
├── docker-compose.yml
└── README.md
```

## Сценарий демонстрации (для защиты)

1. **Дашборд (`/`)** — увидеть 120 объектов, разбиение по статусу, отказы за год.
2. **Реестр (`/assets`)** — отфильтровать по типу «Трансформаторы», открыть карточку.
3. **Карточка объекта** — нажать «🔮 Пересчитать риск», показать цифровой health-score, downstream-зависимости.
4. **Прогноз отказов (`/risk`)** — нажать «Пересчитать риски всех объектов», затем «Переобучить модель» (показать AUC, F1, важные признаки).
5. **План ТОиР (`/maintenance`)** — нажать «Сгенерировать план», показать таблицу с приоритетами и стоимостью.
6. **Аналитика (`/analytics`)** — графики отказов по месяцам, по тяжести.
7. **Swagger (`http://localhost:8000/docs`)** — показать REST API.

## REST API (краткий список)

| Группа       | Основные эндпоинты                                     |
|--------------|--------------------------------------------------------|
| Auth         | `POST /api/auth/token`, `GET /api/auth/me`             |
| Assets       | `GET /api/assets`, `GET /api/assets/{id}`, `POST /api/assets` |
| Inspections  | `POST /api/inspections`, `GET /api/inspections/asset/{id}` |
| Repairs      | `POST /api/repairs`, `GET /api/repairs/asset/{id}`     |
| Failures     | `GET /api/failures`, `POST /api/failures`              |
| Risk / ML    | `POST /api/risk/calculate/{id}`, `POST /api/risk/calculate-all`, `POST /api/risk/retrain`, `GET /api/risk/model-metrics` |
| Maintenance  | `POST /api/maintenance/generate`, `GET /api/maintenance/plans` |
| Twin         | `POST /api/twin/rebuild`, `GET /api/twin/graph`, `GET /api/twin/node/{id}` |
| Analytics    | `GET /api/analytics/summary`, `/failures-by-month`, `/risk-distribution`, `/top-risk-assets` |

Полный список — Swagger UI на `/docs`.

## Подробная документация

См. **[docs/architecture.md](docs/architecture.md)** — описание схемы БД, алгоритма генерации синтетики, цифровой копии, ML-модели и планировщика. Этот документ можно прямо включать в пояснительную записку.

## Лицензия

MIT — учебный проект.
