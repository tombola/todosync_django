"""Task queue abstraction for Todoist API calls.

All Todoist API calls are routed through this module. The Conditional
Dispatcher runs calls synchronously when the queue is idle and no rate
limit is active; otherwise tasks are enqueued via huey (see huey_tasks.py).

To swap queue backends in future, replace huey_tasks.py and update the
_enqueue_* helpers below — the public interface here stays the same.
"""

import logging

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

RATE_LIMIT_CACHE_KEY = "todoist_api_rate_limited"
RATE_LIMIT_DEFAULT_BACKOFF = 60  # seconds


class RateLimitError(Exception):
    """Raised when Todoist returns HTTP 429 Too Many Requests."""


# ---------------------------------------------------------------------------
# Rate-limit state (stored in Django cache so it survives across requests)
# ---------------------------------------------------------------------------


def is_rate_limited() -> bool:
    return bool(cache.get(RATE_LIMIT_CACHE_KEY))


def set_rate_limited(retry_after: int = RATE_LIMIT_DEFAULT_BACKOFF) -> None:
    cache.set(RATE_LIMIT_CACHE_KEY, True, timeout=retry_after)
    logger.warning("Todoist rate limit hit; pausing synchronous calls for %ds", retry_after)


# ---------------------------------------------------------------------------
# Queue load check
# ---------------------------------------------------------------------------


def _is_under_load() -> bool:
    """Return True if the huey queue has too many pending tasks."""
    threshold = getattr(settings, "TODOIST_QUEUE_THRESHOLD", 10)
    try:
        from django_huey import get_queue

        q = get_queue("todoist")
        count = q.pending_count()
        if count >= threshold:
            logger.debug("Queue under load: %d pending tasks (threshold %d)", count, threshold)
            return True
        return False
    except Exception:
        # Fail safe: if we can't check, assume not under load
        return False


def should_dispatch_sync() -> bool:
    """Return True when synchronous execution is appropriate."""
    return not is_rate_limited() and not _is_under_load()


# ---------------------------------------------------------------------------
# Public dispatch functions
# ---------------------------------------------------------------------------


def dispatch_create_tasks(template, token_values, form_description=""):
    """Create tasks from a template, synchronously or queued.

    Runs synchronously and returns the full result dict when the queue is
    healthy and no rate limit is active.  Falls back to queuing (returning
    a sentinel dict) when rate-limited or the queue is under load.
    """
    if not should_dispatch_sync():
        logger.info(
            "Queuing create_tasks for template '%s' (rate_limited=%s, under_load=%s)",
            template.title,
            is_rate_limited(),
            _is_under_load(),
        )
        _enqueue_create_tasks(template.pk, token_values, form_description)
        return {"queued": True, "parent_task_instance": None, "task_count": 0}

    from .todoist_api import _create_tasks_impl, get_api_client

    api = get_api_client()
    try:
        return _create_tasks_impl(api, template, token_values, form_description)
    except RateLimitError as exc:
        logger.warning("Rate limit encountered during create_tasks; re-queuing: %s", exc)
        set_rate_limited()
        _enqueue_create_tasks(template.pk, token_values, form_description)
        return {"queued": True, "parent_task_instance": None, "task_count": 0}


def dispatch_move_task(task_id: str, section_id: str) -> None:
    """Move a Todoist task to a section, synchronously or queued."""
    if not should_dispatch_sync():
        _enqueue_move_task(task_id, section_id)
        return

    from .todoist_api import get_api_client

    api = get_api_client()
    if not api:
        return
    try:
        api.move_task(task_id=task_id, section_id=section_id)
    except RateLimitError as exc:
        logger.warning("Rate limit encountered during move_task; re-queuing: %s", exc)
        set_rate_limited()
        _enqueue_move_task(task_id, section_id)


# ---------------------------------------------------------------------------
# Internal enqueuers (lazy-import huey_tasks to keep abstraction clean)
# ---------------------------------------------------------------------------


def _enqueue_create_tasks(template_id, token_values, form_description):
    from .huey_tasks import create_tasks_async

    logger.info("Enqueuing create_tasks_async for template_id=%s", template_id)
    create_tasks_async(template_id, token_values, form_description)


def _enqueue_move_task(task_id, section_id):
    from .huey_tasks import move_task_async

    logger.info("Enqueuing move_task_async for task_id=%s", task_id)
    move_task_async(task_id, section_id)
