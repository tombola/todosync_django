# Task Queue: Todoist API Call Dispatching

## Overview

All Todoist API calls are routed through a **Conditional Dispatcher** (`task_queue.py`) that decides whether to execute a call synchronously or defer it to a background worker via [huey](https://huey.readthedocs.io/).

```
view / webhook handler
        │
        ▼
create_tasks_from_template()   ← todoist_api.py (public entry point)
        │
        ▼
dispatch_create_tasks()        ← task_queue.py
        │
        ├── should_dispatch_sync()? ──YES──► _create_tasks_impl() [synchronous, returns result]
        │        │
        │        └── RateLimitError caught ──► set_rate_limited() ──► enqueue
        │
        └──────────────────────NO───────────► create_tasks_async() [huey background task]
```

The same pattern applies to `dispatch_move_task()` / `move_task_async()`.

---

## Synchronous vs Queued Execution

`should_dispatch_sync()` returns `True` — and the call runs immediately — when **both** conditions hold:

| Condition | Check | Setting |
|-----------|-------|---------|
| Not rate-limited | `django.core.cache` key `todoist_api_rate_limited` absent | Auto-cleared after `Retry-After` seconds |
| Queue not under load | `get_queue('todoist').pending_count() < TODOIST_QUEUE_THRESHOLD` | `TODOIST_QUEUE_THRESHOLD` (default `10`) |

When queued, `create_tasks_from_template` returns `{"queued": True, "parent_task_instance": None, "task_count": 0}`. The view displays an informational message instead of a success count.

---

## Configuration

### 1. Add `django_huey` to `INSTALLED_APPS`

```python
INSTALLED_APPS = [
    ...
    "django_huey",
    "todosync",
    ...
]
```

### 2. Configure `DJANGO_HUEY`

**SQLite (development / low-volume):**

```python
DJANGO_HUEY = {
    "default": "todoist",
    "queues": {
        "todoist": {
            "huey_class": "huey.SqliteHuey",
            "name": "todoist-tasks",
            "filename": str(BASE_DIR / "data" / "huey.db"),
            "immediate": False,
        },
    },
}
```

**Redis (production / high-volume):**

```python
DJANGO_HUEY = {
    "default": "todoist",
    "queues": {
        "todoist": {
            "huey_class": "huey.RedisHuey",
            "name": "todoist-tasks",
            "url": "redis://localhost:6379/?db=1",
            "immediate": False,
        },
    },
}
```

### 3. Optional settings

```python
# Max pending tasks before the dispatcher falls back to queuing (default 10)
TODOIST_QUEUE_THRESHOLD = 10
```

### 4. Start the worker (development / production)

```bash
python manage.py run_huey
```

---

## Testing

Set `immediate=True` in your test settings so huey runs tasks synchronously
in the calling thread — no consumer process needed and `unittest.mock.patch`
contexts remain active:

```python
# settings/test.py
DJANGO_HUEY = {
    "default": "todoist",
    "queues": {
        "todoist": {
            "huey_class": "huey.MemoryHuey",   # no file I/O during test setup
            "name": "todoist-tasks-test",
            "immediate": True,
        },
    },
}
```

`MemoryHuey` is used instead of `SqliteHuey` because `SqliteHuey` initialises
its storage file during `__init__` before `immediate_use_memory` can swap it
out — `MemoryHuey` avoids this entirely.

With `immediate=True`, `pending_count()` always returns `0`, so the queue
threshold is never reached and the synchronous path is always taken in tests.

---

## Swapping Queue Backends

The abstraction boundary is:

- **`task_queue.py`** — public interface (`dispatch_create_tasks`, `dispatch_move_task`, `RateLimitError`, `should_dispatch_sync`). This file does **not** change when swapping backends.
- **`huey_tasks.py`** — concrete task definitions. Replace this file with your new backend's task functions.
- **`task_queue._enqueue_*`** — update these two helpers to import from the new task module.

### Example: switching to `django-background-tasks`

1. Replace `huey_tasks.py`:

```python
from background_task import background

@background(schedule=0)
def create_tasks_async(template_id, token_values, form_description=""):
    from .models import BaseTaskGroupTemplate
    from .todoist_api import _create_tasks_impl, get_api_client
    api = get_api_client()
    template = BaseTaskGroupTemplate.objects.get(pk=template_id)
    _create_tasks_impl(api, template, token_values, form_description)

@background(schedule=0)
def move_task_async(task_id, section_id):
    from .todoist_api import get_api_client
    api = get_api_client()
    if api:
        api.move_task(task_id=task_id, section_id=section_id)
```

2. Update `task_queue._enqueue_*` imports from `.huey_tasks` → new module.
3. Remove `django_huey` from `INSTALLED_APPS`; add `background_task`.
4. No changes to `todoist_api.py`, `views.py`, or tests.

---

## Rate Limit Handling

When the Todoist API returns HTTP 429, `_call_api()` in `todoist_api.py` raises
`RateLimitError`. The dispatcher catches this, calls `set_rate_limited()` which
sets a Django cache key with the `Retry-After` timeout (default 60 s), then
re-enqueues the failed operation.

Subsequent calls within the backoff window skip synchronous execution entirely
(`is_rate_limited()` returns `True`) and go straight to the queue.
