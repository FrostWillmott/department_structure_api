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
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/department_api` | Асинхронный URL подключения к PostgreSQL |
| `TEST_DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/department_api_test` | URL тестовой базы (устанавливается автоматически в Docker) |

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
- `GET /departments/{id}` принимает параметры `depth` (1–5), `include_employees` и `sort_employees_by`.
- `DELETE` с `mode=cascade` удаляет отдел, все дочерние отделы и всех их сотрудников.
- `DELETE` с `mode=reassign` перемещает прямых сотрудников в `reassign_to_department_id` перед удалением.
