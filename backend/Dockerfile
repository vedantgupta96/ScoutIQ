# ScoutIQ API image. Railway/Render build this automatically when the service
# root directory is `backend` (a Dockerfile beats builder auto-detection, which
# does not install a bare setuptools pyproject). Local use:
#   docker build -t scoutiq-api . && docker run -p 8000:8000 --env-file .env scoutiq-api
FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Everything the API serves ships in the package tree: code, the committed
# model.joblib, and the LLM gold set + eval artifact. ETL/training never run
# in this image. All deps have manylinux wheels and psycopg[binary] bundles
# libpq, so no apt packages are required.
COPY pyproject.toml ./
COPY scoutiq ./scoutiq
RUN pip install .

EXPOSE 8000

# $PORT is injected by the platform; the default keeps local docker runs working.
CMD ["sh", "-c", "uvicorn scoutiq.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
