FROM python:3.12-slim AS base

WORKDIR /app

RUN pip install uv --no-cache-dir

COPY pyproject.toml uv.lock ./


FROM base AS production

RUN uv sync --frozen --no-dev

COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini main.py ./

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]


FROM base AS test

RUN uv sync --frozen --extra dev

COPY . .

ENV COVERAGE_CORE=sysmon

CMD ["uv", "run", "pytest", "-v"]
