# Department Structure API

REST API для управления организационной структурой: иерархические отделы и сотрудники.

## Технологии

- **FastAPI** — асинхронный веб-фреймворк
- **SQLAlchemy 2.0** (async) + **asyncpg** — доступ к базе данных
- **PostgreSQL 16** — основная база данных
- **Alembic** — миграции
- **pydantic-settings** — конфигурация
- **ruff** + **mypy** — линтинг и проверка типов
- **pytest** + **pytest-asyncio** + **httpx** — тестирование

## Быстрый старт

```bash
docker-compose up --build
```

Приложение будет доступно по адресу [http://localhost:8000](http://localhost:8000).  
Интерактивная документация API: [http://localhost:8000/docs](http://localhost:8000/docs).

Миграции запускаются автоматически при старте контейнера.

## Локальная разработка

**Требования:** Python 3.12+, [uv](https://docs.astral.sh/uv/), PostgreSQL на localhost:5432.

```bash
# Установка зависимостей
uv sync --extra dev

# Установка pre-commit хуков
uv run pre-commit install

# Настройка URL базы данных
cp .env.example .env
# При необходимости отредактируйте .env

# Запуск миграций
uv run alembic upgrade head

# Запуск сервера разработки
uv run uvicorn main:app --reload
```

## Запуск тестов

Тесты запускаются в Docker против выделенного экземпляра PostgreSQL — локальная настройка не требуется:

```bash
docker compose --profile test up --build --abort-on-container-exit --exit-code-from test
```

Отчёт о покрытии выводится в логах контейнера.

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/department_api` | URL БД для локального запуска приложения и миграций |
| `TEST_DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/department_api_test` | URL БД для локального запуска тестов |
| `COMPOSE_DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@db:5432/department_api` | URL БД для сервиса `app` внутри `docker compose` |
| `COMPOSE_TEST_DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@db_test:5432/department_api_test` | URL БД для сервиса `test` внутри `docker compose --profile test` |

## Обзор API

| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/departments/` | Создать отдел |
| `GET` | `/departments/{id}` | Получить отдел с сотрудниками и поддеревом |
| `PATCH` | `/departments/{id}` | Переименовать или переместить отдел |
| `DELETE` | `/departments/{id}` | Удалить (каскадный или режим переназначения) |
| `POST` | `/departments/{id}/employees/` | Добавить сотрудника в отдел |

### Ключевые особенности

- Названия отделов **уникальны в пределах одного родителя**.
- Перемещение отклоняется, если создаёт **цикл** в дереве.
- `GET /departments/{id}` принимает параметры `depth` (1–5), `include_employees` и `sort_employees_by`, и возвращает объект вида:
  - `department` — данные запрошенного отдела
  - `employees` — сотрудники запрошенного отдела (опционально, в зависимости от `include_employees`)
  - `children` — рекурсивное поддерево дочерних отделов

Пример ответа `GET /departments/{id}`:

```json
{
  "department": {
    "id": 1,
    "name": "Engineering",
    "parent_id": null,
    "created_at": "2026-05-21T10:00:00Z"
  },
  "employees": [
    {
      "id": 10,
      "department_id": 1,
      "full_name": "Ivan Ivanov",
      "position": "Backend Developer",
      "hired_at": "2024-02-01",
      "created_at": "2026-05-21T10:01:00Z"
    }
  ],
  "children": [
    {
      "id": 2,
      "name": "Platform",
      "parent_id": 1,
      "created_at": "2026-05-21T10:02:00Z",
      "children": []
    }
  ]
}
```
- `DELETE` с `mode=cascade` удаляет отдел, все дочерние отделы и всех их сотрудников.
- `DELETE` с `mode=reassign` перемещает прямых сотрудников в `reassign_to_department_id` перед удалением.
