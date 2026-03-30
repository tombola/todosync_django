"""Callback registry for todosync webhook events.

External apps register callbacks here to be notified when webhook events fire.
Callbacks are called by fire_rule_callbacks() in todoist_api.py.
"""

_rule_callbacks = []
_shorthand_callbacks = []


def register_rule_callback(fn):
    """Register a callable to be called on webhook rule events.

    The callable will be called as: fn(trigger, task, item)
    where:
      trigger  - str event name e.g. 'completed_task'
      task     - todosync.models.Task instance (the matched Django task)
      item     - todosync.schemas.TodoistItem instance (webhook payload item)
    """
    _rule_callbacks.append(fn)


def register_shorthand_callback(fn):
    """Register a callable for untracked item:added webhook events.

    The callable will be called as: fn(item)
    where:
      item - todosync.schemas.TodoistItem instance (webhook payload item)
    """
    _shorthand_callbacks.append(fn)


def fire_shorthand_callbacks(item):
    """Call all registered shorthand callbacks with the given item.

    Exceptions from individual callbacks are caught and logged so one
    bad callback does not prevent others from running.
    """
    import logging

    logger = logging.getLogger(__name__)

    for fn in _shorthand_callbacks:
        try:
            fn(item)
        except Exception:
            logger.exception(
                "Shorthand callback %r raised an exception (item_id=%s)",
                fn,
                getattr(item, "id", None),
            )


def fire_rule_callbacks(trigger, task, item):
    """Call all registered callbacks with the given trigger, task, and item.

    Exceptions from individual callbacks are caught and logged so one
    bad callback does not prevent others from running.
    """
    import logging

    logger = logging.getLogger(__name__)

    for fn in _rule_callbacks:
        try:
            fn(trigger, task, item)
        except Exception:
            logger.exception(
                "Rule callback %r raised an exception (trigger=%s, task_pk=%s)",
                fn,
                trigger,
                getattr(task, "pk", None),
            )
