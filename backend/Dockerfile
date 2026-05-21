FROM python:3.11-slim

WORKDIR /app

# Системные пакеты НЕ нужны: используем psycopg2-binary (precompiled wheel),
# а bcrypt / scikit-learn / numpy / pandas тоже идут как wheel-ы.
# Это убирает зависимость от deb.debian.org при сборке.

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/ml_models

EXPOSE 8000
