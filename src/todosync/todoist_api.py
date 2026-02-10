"""Todoist-specific API integration.

All direct interaction with the Todoist API lives here. If swapping to a
different task-management backend, this module is what gets replaced.
"""

import base64
import hashlib
import hmac
import logging
import sys

from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from pydantic import ValidationError
from todoist_api_python.api import TodoistAPI

from .models import Task
from .schemas import TodoistWebhookPayload, WebhookEventType
from .utils import substitute_tokens

logger = logging.getLogger(__name__)


def get_api_client():
    """Return a configured TodoistAPI client, or None if no token is set."""
    api_token = getattr(settings, 'TODOIST_API_TOKEN', None)
    if not api_token:
        return None
    return TodoistAPI(api_token)


def create_tasks_from_template(api, template, token_values, site, form_description='', debug=False):
    """Create Todoist tasks from template and persist tracking records.

    Args:
        api: TodoistAPI instance (can be None if debug=True)
        template: BaseTaskGroupTemplate instance
        token_values: Dict of token replacements (field_name -> value)
        site: Wagtail Site instance for accessing settings
        form_description: Optional description from the creation form
        debug: If True, print debug info instead of posting to API

    Returns:
        Dict with 'parent_task_instance' and 'task_count'.
    """
    if debug:
        print("\n" + "=" * 80, file=sys.stderr)
        print(f"DEBUG: Creating tasks from template: {template.title}", file=sys.stderr)
        print(f"DEBUG: Token values: {token_values}", file=sys.stderr)
        print("=" * 80 + "\n", file=sys.stderr)

    # Create the parent task model instance
    parent_task_model = template.get_parent_task_model()
    if not parent_task_model:
        raise ValueError("Template has no task_type configured")

    instance_kwargs = {'template': template}
    for field_name in parent_task_model.get_token_field_names():
        if field_name in token_values:
            instance_kwargs[field_name] = token_values[field_name]

    parent_task_instance = parent_task_model(**instance_kwargs)

    # Get title and description from the instance
    parent_title = parent_task_instance.get_parent_task_title()

    # Build description from instance + template + form
    description_parts = []
    instance_description = parent_task_instance.get_description()
    if instance_description:
        description_parts.append(instance_description)
    if template.description:
        template_description = substitute_tokens(template.description, token_values)
        description_parts.append(template_description)
    if form_description:
        form_desc = substitute_tokens(form_description, token_values)
        description_parts.append(form_desc)

    parent_description = '\n\n'.join(description_parts) if description_parts else ''

    # Build Todoist task params
    task_params = {'content': parent_title}
    if parent_description:
        task_params['description'] = parent_description

    project_id = template.get_effective_project_id(site)
    if project_id:
        task_params['project_id'] = project_id

    task_count = 0

    if debug:
        import random
        print(f"Parent Task: {parent_title}", file=sys.stderr)
        if parent_description:
            print(f"  Description: {parent_description}", file=sys.stderr)
        if project_id:
            print(f"  Project ID: {project_id}", file=sys.stderr)
        parent_todo_id = f"debug_{random.randint(1000, 9999)}"
        task_count += 1
    else:
        try:
            print(f"DEBUG: Creating parent task with params: {task_params}", file=sys.stderr)
            todoist_parent = api.add_task(**task_params)
            parent_todo_id = todoist_parent.id
            print(f"DEBUG: Parent task created successfully: {parent_todo_id}", file=sys.stderr)
        except Exception as e:
            print(f"ERROR: Failed to create parent task: {e}", file=sys.stderr)
            print(f"ERROR: Task params were: {task_params}", file=sys.stderr)
            raise
        task_count += 1

    # Save the parent task instance with external ID
    parent_task_instance.todo_id = parent_todo_id
    if not debug:
        parent_task_instance.save()

    # Create child tasks from template
    for task_data in template.tasks:
        if task_data.block_type == 'task':
            task_block = task_data.value
            task_count += _create_task_recursive(
                api, task_block, token_values,
                parent_todo_id=parent_todo_id,
                parent_task_record=None,
                debug=debug,
                indent=1,
            )

    if debug:
        print("\n" + "=" * 80, file=sys.stderr)
        print(f"DEBUG: Total tasks created: {task_count}", file=sys.stderr)
        print("=" * 80 + "\n", file=sys.stderr)

    return {
        'parent_task_instance': parent_task_instance,
        'task_count': task_count,
    }


def _create_task_recursive(api, task_block, token_values, parent_todo_id=None,
                           parent_task_record=None, debug=False, indent=0):
    """Recursively create a task and its subtasks.

    Args:
        api: TodoistAPI instance (can be None if debug=True)
        task_block: Task block data from StreamField
        token_values: Dict of token replacements
        parent_todo_id: External parent task ID
        parent_task_record: Parent Task instance, or None for top-level tasks
        debug: If True, print debug info instead of posting to API
        indent: Indentation level for debug output

    Returns:
        Count of tasks created.
    """
    title = substitute_tokens(task_block['title'], token_values)

    labels = []
    if task_block.get('labels'):
        labels = [label.strip() for label in task_block['labels'].split(',') if label.strip()]

    task_params = {'content': title}
    if labels:
        task_params['labels'] = labels
    if parent_todo_id:
        task_params['parent_id'] = parent_todo_id

    count = 0

    if debug:
        import random
        indent_str = "  " * indent
        print(f"{indent_str}Task: {title}", file=sys.stderr)
        if labels:
            print(f"{indent_str}  Labels: {', '.join(labels)}", file=sys.stderr)
        created_todo_id = f"debug_{random.randint(1000, 9999)}"
        count += 1
    else:
        try:
            print(f"DEBUG: Creating task with params: {task_params}", file=sys.stderr)
            created_task = api.add_task(**task_params)
            created_todo_id = created_task.id
            print(f"DEBUG: Task created successfully: {created_todo_id}", file=sys.stderr)
        except Exception as e:
            print(f"ERROR: Failed to create task: {e}", file=sys.stderr)
            print(f"ERROR: Task params were: {task_params}", file=sys.stderr)
            raise
        count += 1

    # Create Task record (parent_task links to either the parent Task or None for top-level)
    task_record = None
    if not debug:
        task_record = Task.objects.create(
            parent_task=parent_task_record,
            todo_id=created_todo_id,
            title=title,
        )

    # Recurse into subtasks
    if task_block.get('subtasks'):
        for subtask_data in task_block['subtasks']:
            count += _create_task_recursive(
                api, subtask_data, token_values,
                parent_todo_id=created_todo_id,
                parent_task_record=task_record if not debug else None,
                debug=debug,
                indent=indent + 1,
            )

    return count


def _verify_webhook_signature(request):
    """Verify the HMAC-SHA256 signature from Todoist.

    Returns True if TODOIST_WEBHOOK_SECRET is not configured (verification disabled).
    """
    secret = getattr(settings, 'TODOIST_WEBHOOK_SECRET', None)
    if not secret:
        return True

    signature = request.headers.get('X-Todoist-Hmac-SHA256', '')
    digest = hmac.new(secret.encode(), request.body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(signature, expected)


@csrf_exempt
@require_POST
def todoist_webhook(request):
    """Receive webhook events from Todoist and sync task state.

    Handles item:added, item:updated, item:deleted, item:completed,
    and item:uncompleted events. Updates the local Task record's
    completed status and section when a matching todo_id is found.
    """
    if not _verify_webhook_signature(request):
        logger.warning("Todoist webhook signature verification failed")
        return HttpResponseForbidden()

    try:
        payload = TodoistWebhookPayload.model_validate_json(request.body)
    except ValidationError:
        logger.exception("Invalid Todoist webhook payload")
        return HttpResponseBadRequest("Invalid payload")

    item = payload.event_data
    event = payload.event_name

    try:
        task = Task.objects.get(todo_id=item.id)
    except Task.DoesNotExist:
        # Not a task we're tracking — acknowledge and ignore
        return HttpResponse(status=200)

    update_fields = []

    if event in (WebhookEventType.ITEM_COMPLETED, WebhookEventType.ITEM_DELETED):
        task.completed = True
        update_fields.append('completed')
    elif event == WebhookEventType.ITEM_UNCOMPLETED:
        task.completed = False
        update_fields.append('completed')
    elif event in (WebhookEventType.ITEM_UPDATED, WebhookEventType.ITEM_ADDED):
        if item.checked != task.completed:
            task.completed = item.checked
            update_fields.append('completed')

    # Sync section changes for any event that carries section_id
    if item.section_id is not None and item.section_id != task.todo_section_id:
        task.todo_section_id = item.section_id
        update_fields.append('todo_section_id')

    if update_fields:
        task.save(update_fields=update_fields)
        logger.info("Webhook %s: updated task %s (fields: %s)", event, item.id, update_fields)
    else:
        logger.debug("Webhook %s: no changes for task %s", event, item.id)

    return HttpResponse(status=200)
