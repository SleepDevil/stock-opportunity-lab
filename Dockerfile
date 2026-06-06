FROM node:22-bookworm-slim AS frontend-build

WORKDIR /app
COPY frontend/package*.json ./frontend/
RUN npm --prefix frontend ci
COPY frontend ./frontend
RUN npm --prefix frontend run build

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV STOCK_LAB_DATA_DIR=/data
ENV PORT=8000

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl gcc g++ \
  && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./backend/pyproject.toml
COPY backend/app ./backend/app
RUN python -m pip install --upgrade pip \
  && python -m pip install -e ./backend

COPY --from=frontend-build /app/frontend/dist ./frontend/dist
RUN mkdir -p /data

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000}"]

