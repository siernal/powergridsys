# Деплой PowerGrid Maintenance System на Render (без Docker)

Пошаговая инструкция: запушить проект в GitHub и развернуть на render.com три ресурса —
базу данных PostgreSQL, бэкенд (FastAPI) и фронтенд (React/Vite).

Деплой идёт **нативными рантаймами Render** (Python и статический сайт), а не через Docker.

---

## Что уже подготовлено в репозитории

| Файл | Назначение |
|------|-----------|
| `render.yaml` | Blueprint — описывает все три ресурса, Render создаёт их автоматически |
| `.gitignore` | Исключает `node_modules`, кэши, `.env`, обученную модель и т. п. |
| `backend/.python-version` | Версия Python для бэкенда (3.11.9) |

Также внесены правки в код для совместимости с бесплатным тарифом (512 МБ RAM):

- **ML-модель обучается на этапе сборки (build)**, а не при старте сервера — иначе
  `GridSearchCV` с `n_jobs=-1` не помещается в память и/или превышает таймаут.
- Добавлен **облегчённый режим обучения** (`ML_FAST_TRAIN=1`, `ML_N_JOBS=1`).
- `DATABASE_URL` со схемой `postgres://` автоматически приводится к `postgresql://`.
- Список разрешённых CORS-доменов можно задать через `CORS_ORIGINS` (по умолчанию открыт).

---

## Шаг 1. Запушить проект в GitHub

Откройте терминал в папке проекта (`D:\Claude\vkr`) и выполните:

```bash
git init
git add .
git commit -m "PowerGrid Maintenance System — подготовка к деплою на Render"
git branch -M main
git remote add origin https://github.com/<ВАШ_ЛОГИН>/<ВАШ_РЕПОЗИТОРИЙ>.git
git push -u origin main
```

> Если репозиторий на GitHub не пустой (есть README/LICENSE), сначала выполните
> `git pull origin main --allow-unrelated-histories`, разрешите конфликты и затем `git push`.

> При запросе пароля GitHub нужен **Personal Access Token** (Settings → Developer settings →
> Personal access tokens), а не пароль от аккаунта.

---

## Шаг 2. Развернуть всё одним Blueprint

1. Зайдите на [dashboard.render.com](https://dashboard.render.com).
2. Нажмите **New +** → **Blueprint**.
3. Подключите свой GitHub-аккаунт (если ещё не подключён) и выберите репозиторий.
4. Render найдёт `render.yaml` и покажет три ресурса: `powergrid-db`, `powergrid-backend`,
   `powergrid-frontend`. Нажмите **Apply**.
5. Render начнёт сборку. Бэкенд при первой сборке обучает ML-модель — это занимает
   1–2 минуты. Дождитесь статуса **Live** у всех ресурсов.

---

## Шаг 3. Проверить и при необходимости поправить адрес бэкенда

Фронтенд обращается к бэкенду по адресу из переменной `VITE_API_URL`, которая «зашивается»
в сборку. В `render.yaml` указано `https://powergrid-backend.onrender.com`.

Если Render выдал бэкенду другое имя (например, `powergrid-backend-ab12.onrender.com`):

1. Откройте сервис **powergrid-frontend** → вкладка **Environment**.
2. Измените `VITE_API_URL` на реальный URL бэкенда (без `/` в конце).
3. Нажмите **Manual Deploy** → **Deploy latest commit** (нужна пересборка — переменная
   применяется на этапе build).

Адрес бэкенда виден на странице сервиса `powergrid-backend` вверху. Проверить, что он
работает, можно открыв `https://<адрес-бэкенда>/health` — должно вернуться `{"status":"ok"}`.
Документация API: `https://<адрес-бэкенда>/docs`.

---

## Шаг 4. Готово

Откройте URL сервиса **powergrid-frontend** (`https://powergrid-frontend.onrender.com`) —
это и есть рабочее приложение.

---

## Важные особенности бесплатного тарифа Render

- **Засыпание.** Бесплатные сервисы «засыпают» после ~15 минут простоя. Первый запрос
  после сна будит сервис — холодный старт занимает 30–60 секунд. Это нормально.
- **Фоновый симулятор трансформаторов** работает, только пока бэкенд активен; во время сна
  он останавливается и возобновляется при следующем пробуждении. На демонстрацию не влияет.
- **Бесплатная база PostgreSQL** на Render удаляется через 30 дней. Для долгого хранения —
  перейдите на платный план БД или периодически делайте дамп. Данные при этом не критичны:
  при старте бэкенд автоматически наполняет пустую БД демо-данными (скрипт `seed`).
- **Обновление приложения.** Любой `git push` в ветку `main` запускает автоматический
  передеплой соответствующих сервисов.

---

## Если предпочитаете настраивать вручную (без Blueprint)

Создайте ресурсы по очереди через **New +**:

**1) PostgreSQL** → New + → **PostgreSQL**, план Free. Скопируйте **Internal Database URL**.

**2) Backend** → New + → **Web Service**, репозиторий тот же. Настройки:
- Root Directory: `backend`
- Runtime: `Python 3`
- Build Command:
  `pip install -r requirements.txt && python -c "from services.ml_predictor import train_model; train_model('./ml_models/rf_model.pkl')"`
- Start Command:
  `python seed/seed_data.py && uvicorn main:app --host 0.0.0.0 --port $PORT`
- Health Check Path: `/health`
- Environment Variables:
  `DATABASE_URL` = Internal Database URL из шага 1;
  `SECRET_KEY` = любая длинная случайная строка;
  `ML_MODEL_PATH` = `./ml_models/rf_model.pkl`;
  `ML_FAST_TRAIN` = `1`; `ML_N_JOBS` = `1`; `PYTHON_VERSION` = `3.11.9`.

**3) Frontend** → New + → **Static Site**, репозиторий тот же. Настройки:
- Root Directory: `frontend`
- Build Command: `npm install && npx vite build`
- Publish Directory: `dist`
- Environment Variable: `VITE_API_URL` = URL бэкенда из шага 2.
- Redirect/Rewrite Rule: Source `/*` → Destination `/index.html`, тип **Rewrite**
  (вкладка Redirects/Rewrites — нужно для корректной работы маршрутов React Router).
