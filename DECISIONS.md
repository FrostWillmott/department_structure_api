# DECISIONS

> Ключевые архитектурные решения: что сделано, почему именно так и какие были альтернативы.

---

## Содержание

1. [Архитектура: три слоя](#1-архитектура-три-слоя)
2. [Дерево отделов и ноды](#2-дерево-отделов-и-ноды)
3. [Recursive CTE](#3-recursive-cte)
4. [BFS и обнаружение циклов](#4-bfs-и-обнаружение-циклов)
5. [PATCH и model_fields_set](#5-patch-и-model_fields_set)
6. [Удаление: cascade vs reassign](#6-удаление-cascade-vs-reassign)
7. [Каскад: БД + ORM (passive_deletes)](#7-каскад-бд--orm-passive_deletes)
8. [Уникальность имён](#8-уникальность-имён)
9. [Async, сессии, get_db](#9-async-сессии-get_db)
10. [expire_on_commit](#10-expire_on_commit)
11. [Конфигурация и окружения](#11-конфигурация-и-окружения)
12. [SQLAlchemy 2.0: новый синтаксис](#12-sqlalchemy-20-новый-синтаксис)
13. [Тесты](#13-тесты)

---

## 1. Архитектура: три слоя

**Решение:** разделить на `routers/` (HTTP) → `services/` (бизнес-логика) → `database.py` (доступ к БД).

**Почему:**
- Роутеры заняты только HTTP: парсинг запроса, вызов сервиса, преобразование доменных исключений в `HTTPException`.
- Сервисы содержат всю бизнес-логику (валидация, циклы, каскады) и **не знают про HTTP** — их можно тестировать и переиспользовать вне веба.
- Доменные исключения (`app/exceptions.py`) — контракт между слоями: сервис бросает `DepartmentNotFoundError`, роутер решает, что это 404.

**Альтернативы:**
- Repository layer между сервисом и SQLAlchemy. **Не введён осознанно:** на этом масштабе он добавил бы абстракцию без практической выгоды. Сервисы вызывают SQLAlchemy напрямую.
- Вся логика в роутерах — отвергнуто: смешивает HTTP и бизнес-правила, плохо тестируется.

---

## 2. Дерево отделов и ноды

**Решение:** отделы — самоссылающееся дерево через `parent_id` (FK на ту же таблицу). В БД — плоская таблица, в API — вложенное дерево.

```
id | name        | parent_id        Company
1  | Company     | null         ->   ├── Engineering
2  | Engineering | 1                 │    ├── Backend
3  | Backend     | 2                 │    └── Frontend
4  | Frontend    | 2                 └── HR
5  | HR          | 1
```

- `parent_id = null` → корневой отдел.
- `parent_id = X` → ребёнок отдела X.

**Ноды (`DepartmentTreeNode`):** Pydantic-схема для **вложенного** представления.

Три схемы и зачем они:

| Схема | Содержимое | Использование |
|---|---|---|
| `DepartmentBase` | id, name, parent_id, created_at | ответы POST/PATCH (один отдел) |
| `DepartmentTreeNode` | `DepartmentBase` + `children: list[DepartmentTreeNode]` | вложенные дети в ответе GET |
| `DepartmentTreeResponse` | `department` + `employees` + `children` | полный ответ GET |

`DepartmentTreeNode` ссылается сам на себя в `children` → рекурсивная схема → дерево произвольной глубины.

**Почему дерево собирается в коде, а не хранится вложенно:**
- Реляционная БД хранит данные плоско; вложенность — это представление.
- Один и тот же отдел может запрашиваться как корень поддерева с разной глубиной (`depth`), поэтому дерево формируется под конкретный запрос.

---

## 3. Recursive CTE

**Решение:** `GET /departments/{id}` использует рекурсивный CTE в PostgreSQL для получения поддерева одним запросом.

**Почему:**
- Альтернатива — рекурсивно ходить в БД за каждым уровнем (N+1 запросов). CTE делает это одним запросом на стороне БД.
- Альтернатива — `relationship("children")` с lazy loading: легко уводит в N+1 и плохо сочетается с async. Отвергнуто.

**Как работает:**

```sql
WITH RECURSIVE tree AS (
    -- anchor / база: стартовая точка, level = 0
    SELECT id, name, parent_id, created_at, 0 AS level
    FROM departments WHERE id = :dept_id

    UNION ALL

    -- рекурсивная часть: дети тех, кто уже в tree
    SELECT d.id, d.name, d.parent_id, d.created_at, tree.level + 1
    FROM departments d
    JOIN tree ON d.parent_id = tree.id
    WHERE tree.level < :depth
)
SELECT * FROM tree ORDER BY name;
```

Пошагово (PostgreSQL крутит сам):
1. Выполняет anchor → корень в `tree`.
2. Выполняет рекурсивную часть против текущего `tree` → находит детей.
3. Повторяет шаг 2, пока рекурсивная часть возвращает новые строки и пока `level < depth`.
4. Останавливается, когда новых строк нет.

**Важные детали:**
- `level` — искусственная колонка (`literal(0).label("level")` в anchor, `base.c.level + 1` в рекурсии). В таблице её нет — она вычисляется, потому что глубина зависит от того, относительно какого корня считаем.
- `depth` (валидируется 1–5 в роутере) ограничивает глубину: `WHERE level < depth`.
- `.c` (`base.c.id`, `base.c.level`) — доступ к колонкам CTE. Это API SQLAlchemy (`c` = columns), не FastAPI.
- В Python — **один** `await db.execute(...)`; цикл выполняется внутри PostgreSQL.
- Строки 95–117 сервиса лишь **строят** SQL; запрос уходит в БД на `db.execute` (строка 118).

**После CTE** — сборка дерева в Python:

```python
dept_map = { row.id: DepartmentTreeNode(...) for row in rows }  # узлы с пустыми children
for row in rows:
    if row.parent_id in dept_map and row.id != dept_id:
        dept_map[row.parent_id].children.append(dept_map[row.id])
```

**Сотрудники** — отдельным запросом и только для запрошенного отдела (не для всего поддерева). Сортировка по `created_at` или `full_name`. При `include_employees=false` этот запрос пропускается.

---

## 4. BFS и обнаружение циклов

**Решение:** перед сменой `parent_id` собрать всех потомков отдела через BFS и проверить, что новый родитель не среди них.

**Почему BFS, а не CTE здесь:**
- Нужен только набор ID потомков (`set[int]`), не данные с полями.
- Логика проверки живёт в Python рядом с остальной бизнес-логикой PATCH/DELETE.

**Код (`_get_descendants_ids`):**

```python
result: set[int] = set()
queue = [dept_id]
while queue:
    rows = await db.execute(
        select(Department.id).where(Department.parent_id.in_(queue))
    )
    queue = []
    for (child_id,) in rows:
        if child_id not in result:
            result.add(child_id)
            queue.append(child_id)
return result
```

- `queue` стартует с `dept_id` — это точка старта поиска (его дети), сам `dept_id` в `result` не попадает.
- Один SQL-запрос на уровень дерева (`parent_id IN (...)`).
- `while queue` — идиома BFS: «пока есть необработанные узлы». Останавливается, когда детей не нашлось (`queue` пуст).
- `if child_id not in result` — защита от зацикливания при возможной порче данных.

**Применение:**
- PATCH: `if new_parent_id in descendants → CycleDetectedError (409)`.
- DELETE reassign: `if reassign_to_id in descendants → InvalidReassignTargetError (400)`.

**Почему BFS, а не рекурсия в Python:** не упирается в лимит рекурсии, по одному запросу на уровень, проще читать.

---

## 5. PATCH и model_fields_set

**Проблема:** в PATCH нужно отличать три случая:
- поле **не передано** → не менять;
- поле передано как **null** → осмысленное действие (для `parent_id` — перенос в корень);
- поле передано со **значением** → установить.

Обычная проверка `if data.parent_id is None` не различает «не передали» и «передали null».

**Решение:** `model_fields_set` — множество полей, которые реально присутствовали в запросе.

```python
if "parent_id" in data.model_fields_set:
    new_parent_id = data.parent_id   # может быть и None (= в корень)
```

| Тело запроса | `"parent_id" in model_fields_set` | Действие |
|---|---|---|
| `{"name": "X"}` | False | родителя не трогаем |
| `{"parent_id": null}` | True, значение None | перенос в корень |
| `{"parent_id": 5}` | True, значение 5 | перенос под 5 |

**Защита имени от null:** `name: null` запрещён `model_validator`'ом — имя нельзя «обнулить», поле просто опускают. У `parent_id` null разрешён (это валидное «в корень»).

**Порядок проверок в `update_department`:**
1. Отдел существует? иначе 404.
2. Если меняется `parent_id`:
   - не сам на себя → `SelfParentReferenceError` (400);
   - новый родитель существует? иначе 404;
   - новый родитель не потомок (BFS) → `CycleDetectedError` (409);
   - если имя не меняется — проверить уникальность текущего имени под новым родителем.
3. Если меняется `name` — проверить уникальность под эффективным родителем.
4. commit; на `IntegrityError` — rollback и `DuplicateDepartmentNameError`.

---

## 6. Удаление: cascade vs reassign

**Решение:** два режима через query-параметр `mode`.

### cascade

```python
await db.delete(dept)   # БД каскадом удаляет детей и сотрудников
await db.commit()
```

Удаляет отдел, всё поддерево и всех их сотрудников (через `ON DELETE CASCADE`).

### reassign

```python
await db.execute(
    update(Employee)
    .where(Employee.department_id == dept_id)
    .values(department_id=reassign_to_id)
)
await db.delete(dept)
await db.commit()
```

Переносит **только прямых** сотрудников удаляемого отдела в target, затем удаляет отдел. Дочерние отделы и их сотрудники всё равно каскадно удаляются.

| | cascade | reassign |
|---|---|---|
| сотрудники самого отдела | удаляются | переносятся в target |
| дочерние отделы | удаляются | удаляются |
| сотрудники дочерних | удаляются | удаляются |

**Важно понимать:** reassign не «спасает всё поддерево», а только людей из самого удаляемого отдела. Это сознательный контракт: дочерние ветки считаются частью удаляемой структуры.

**Защиты reassign:**
- нет `reassign_to_id` → `InvalidDeleteModeError` (400);
- target == сам отдел → `InvalidReassignTargetError` (400);
- target не существует → `ReassignTargetNotFoundError` (404);
- target — потомок удаляемого (BFS) → `InvalidReassignTargetError` (400). Иначе сотрудники ушли бы в отдел, который тут же удалится каскадом.

---

## 7. Каскад: БД + ORM (passive_deletes)

Каскадное удаление работает на **двух уровнях**, и это согласовано специально:

1. **БД:** FK объявлены с `ON DELETE CASCADE` (и `parent_id`, и `Employee.department_id`). PostgreSQL сам удаляет зависимые строки.
2. **ORM:** `relationship(..., passive_deletes=True)` говорит SQLAlchemy **не** удалять связанные объекты через Python (не делать лишних SELECT + DELETE), а доверить это БД.

**Почему так:**
- Без `passive_deletes=True` SQLAlchemy при `db.delete(dept)` попыталась бы загрузить детей/сотрудников и удалять их по одному → лишние запросы, в async ещё и риск проблем с lazy load.
- С `passive_deletes=True` + `ON DELETE CASCADE` удаление эффективно и атомарно на стороне БД.

Поэтому в сервисе `await db.delete(dept)` удаляет один отдел, а остальное делает БД. В reassign перенос сотрудников делается явным `UPDATE` **до** delete.

---

## 8. Уникальность имён

**Решение:** имя отдела уникально **в пределах одного родителя**, проверка в сервисном слое.

**Почему не DB UNIQUE constraint на `(name, parent_id)`:**
- Корневые отделы имеют `parent_id = NULL`. В PostgreSQL `NULL != NULL`, поэтому уникальный индекс по `(name, parent_id)` **не предотвратит** двух корневых отделов с одинаковым именем.
- Можно было бы сделать unique по `COALESCE(parent_id, 0)`, но выбран сервисный подход — он проще и даёт понятное сообщение об ошибке.

**Реализация:** `_check_name_unique` делает SELECT перед insert/update; плюс `try/except IntegrityError` как страховка от гонки (одновременные запросы).

---

## 9. Async, сессии, get_db

**Решение:** полностью async доступ к БД (`asyncpg` + `AsyncSession`), сессия на запрос через FastAPI dependency.

```python
engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session
```

- **engine** — пул соединений, создаётся один раз на всё приложение.
- **AsyncSessionLocal** — фабрика сессий.
- **get_db** — dependency, отдаёт по сессии на каждый HTTP-запрос.

**Почему `async with` + `yield`:**
- `async with` гарантирует, что сессия закроется и соединение вернётся в пул — при успехе и при ошибке (аналог `try/finally`).
- `yield` отдаёт сессию роутеру и держит `async with` открытым на время запроса. После того как endpoint завершился (return или исключение), FastAPI **продолжает** генератор после `yield` → срабатывает `__aexit__` → сессия закрывается.
- Соединение освобождается **не во время** запроса, а в его конце — это и нужно (иначе сессия закрылась бы до commit).
- Гарантию завершения teardown даёт **FastAPI** (lifecycle dependency), не сам контекстный менеджер.

**Почему async вообще:** FastAPI — async; пока запрос ждёт ответа PostgreSQL, event loop обслуживает другие запросы. Синхронный драйвер блокировал бы сервер.

**Никакого lazy loading:** все связи грузятся явно через `select()` — чтобы не ловить N+1 и ошибки lazy load в async.

---

## 10. expire_on_commit

**Решение:** `expire_on_commit=False` в фабрике сессий.

**Что это:** по умолчанию (`True`) после `commit()` SQLAlchemy помечает все ORM-объекты как expired — при следующем обращении к любому атрибуту делается новый SELECT. С `False` атрибуты остаются доступны без похода в БД.

**Почему важно здесь:**
- В роутере после сервиса вызывается `DepartmentBase.model_validate(dept)`, который читает `dept.id`, `dept.name` и т.д.
- При `expire_on_commit=True` это вызвало бы lazy reload после commit; в async это лишний запрос или ошибка (если сессия уже закрывается).
- С `False` чтение полей — обычный доступ к атрибутам Python-объекта.

**Уточнение, чего это НЕ значит:**
- Это **не snapshot базы данных**. Это сохранение уже загруженных полей **одного** ORM-объекта в памяти.
- Если другой запрос изменит ту же строку, объект в памяти не обновится автоматически.

**Связь с `refresh`:** `db.refresh(dept)` после commit подтягивает server defaults (`id`, `created_at`). `expire_on_commit=False` гарантирует, что эти значения останутся доступны при сборке ответа.

---

## 11. Конфигурация и окружения

**Решение:** `pydantic-settings`; `DATABASE_URL` из окружения с дефолтом в коде.

```python
class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/department_api"
    model_config = {"env_file": ".env", "extra": "ignore"}

settings = Settings()
```

- Приоритет: переменная окружения → `.env` → дефолт в коде.
- `extra: "ignore"` — посторонние переменные окружения не ломают загрузку.
- `settings = Settings()` — module-level instance (де-факто синглтон за счёт кэша импортов; **не** паттерн Singleton).

**Про дублирование URL (local vs Docker):**
- Локально хост БД — `localhost`; в Docker — сервис `db` внутри сети compose. Поэтому URL разные.
- В compose `DATABASE_URL` задаётся напрямую в `environment`; `.env` в production-образ не копируется.
- Credentials повторяются в нескольких местах (`config.py` default, `.env`, `docker-compose.yml`) — для тестового проекта приемлемо; в проде лучше собирать URL из частей (`${POSTGRES_USER}` и т.д.), чтобы был один источник истины.

---

## 12. SQLAlchemy 2.0: новый синтаксис

**Решение:** typed mappings — `Mapped[...]` + `mapped_column(...)`.

```python
id: Mapped[int] = mapped_column(Integer, primary_key=True)
parent_id: Mapped[int | None] = mapped_column(ForeignKey(...), nullable=True)
employees: Mapped[list["Employee"]] = relationship(...)
```

**Почему лучше старого (`id = Column(...)`):**
- Полная типизация: mypy и IDE знают типы полей (`dept.parent_id` → `int | None`).
- Явное разделение колонок (`mapped_column`) и связей (`relationship`).
- Единый стиль с остальным 2.0 API (`select()` вместо `session.query()`).

**Важные уточнения:**
- Это синтаксис **SQLAlchemy**, не Alembic. Alembic лишь читает `Base.metadata`.
- SQLAlchemy 2.0 **обратно совместим**: старый declarative-синтаксис тоже работает. Новый — рекомендованный стиль, не требование для запуска.

**Про `Base`:** общий `DeclarativeBase` нужен, чтобы все модели были в одном `metadata` (иначе у каждой свой реестр → Alembic и relationships ломаются). Лежит в `database.py` (инфраструктура), модели импортируют его — направление зависимостей `models → database`, без циклов.

---

## 13. Тесты

**Решение:** интеграционные тесты против реального PostgreSQL в Docker.

- Отдельная БД `department_api_test`, сервис `db_test` (Docker compose profile `test`).
- `conftest.py`: `alembic upgrade head` перед тестами, `downgrade base` после — проверяет и сами миграции.
- `dependency_overrides[get_db]` — подмена сессии на тестовую (тестовый engine/sessionmaker).
- `httpx.AsyncClient` + `ASGITransport(app=app)` — запросы к приложению без поднятия реального HTTP-сервера.
- `TEST_DATABASE_URL` инжектится compose; локально дефолт на `localhost`.

**Почему реальная БД, а не моки:** проверяются настоящие FK, `ON DELETE CASCADE`, поведение `NULL` в уникальности, recursive CTE — это невозможно достоверно замокать.