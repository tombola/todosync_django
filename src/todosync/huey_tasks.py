"""Huey task definitions for Todoist API background operations.

These tasks are enqueued by task_queue._enqueue_* when the Conditional
Dispatcher decides not to run synchronously (rate-limited or queue under load).

To swap queue backends, replace this module and update task_queue._enqueue_*
to import from the new module instead.

All imports are deferred to call time so that:
  - unittest.mock.patch on todosync.todoist_api.get_api_client works in tests
  - App startup is not slowed by eager imports
"""

from django_huey import db_task


@db_task(queue="todoist")
def create_tasks_async(template_id, token_values, form_description=""):
    """Background task: create all tasks from a template."""
    from .models import BaseTaskGroupTemplate
    from .todoist_api import _create_tasks_impl, get_api_client

    api = get_api_client()
    template = BaseTaskGroupTemplate.objects.get(pk=template_id)
    _create_tasks_impl(api, template, token_values, form_description)


@db_task(queue="todoist")
def move_task_async(task_id, section_id):
    """Background task: move a Todoist task to a different section."""
    from .todoist_api import get_api_client

    api = get_api_client()
    if api:
        api.move_task(task_id=task_id, section_id=section_id)
