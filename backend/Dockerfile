FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps chromium

RUN useradd --create-home --uid 10001 app && mkdir -p /app/storage && chown app /app/storage
COPY --chown=app . .
USER app

EXPOSE 8000

# Behind a reverse proxy, set FORWARDED_ALLOW_IPS to the proxy's address so login rate
# limits see each user's real IP (uvicorn reads it with --proxy-headers).
ENV FORWARDED_ALLOW_IPS=127.0.0.1

# API only; background work runs in the worker service (python -m app.worker).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
