"""Todoist-specific API integration.

All direct interaction with the Todoist API lives here. If swapping to a
different task-management backend, this module is what gets replaced.
"""

import base64
import hashlib
import hmac
import logging
from datetime import date

from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from pydantic import ValidationError
from todoist_api_python.api import TodoistAPI

from .models import BaseParentTask, Task
from .schemas import TodoistWebhookPayload, WebhookEventType
from .utils import substitute_tokens

logger = logging.getLogger(__name__)


def get_api_client():
    """Return a configured TodoistAPI client, or None if no token is set."""
    api_token = getattr(settings, "TODOIST_API_TOKEN", None)
    if not api_token:
        return None
    return TodoistAPI(api_token)


def create_tasks_from_template(api, template, token_values, form_description="", dry_run=False):
    """Create Todoist tasks from template and persist tracking records.

    Args:
        api: TodoistAPI instance (can be None if dry_run=True)
        template: BaseTaskGroupTemplate instance
        token_values: Dict of token replacements (field_name -> value)
        form_description: Optional description from the creation form
        dry_run: If True, skip API calls and DB writes; log planned actions at DEBUG level

    Returns:
        Dict with 'parent_task_instance' and 'task_count'.
    """
    logger.info(
        "Creating tasks from template: '%s', tokens=%s, project=%s",
        template.title,
        token_values,
        template.get_effective_project_id(),
    )

    if dry_run:
        logger.debug("Dry run: creating tasks from template '%s'", template.title)
        logger.debug("Dry run: token values: %s", token_values)

    # Create the parent task model instance
    parent_task_model = template.get_parent_task_model()
    if not parent_task_model:
        raise ValueError("Template has no task_type configured")

    instance_kwargs = {"template": template}
    for field_name in parent_task_model.get_token_field_names():
        if field_name in token_values:
            instance_kwargs[field_name] = token_values[field_name]

    parent_task_instance = parent_task_model(**instance_kwargs)

    # Get title and description from the instance
    parent_title = parent_task_instance.get_parent_task_title()
    parent_task_instance.title = parent_title

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

    parent_description = "\n\n".join(description_parts) if description_parts else ""

    # Build Todoist task params
    task_params = {"content": parent_title}
    if parent_description:
        task_params["description"] = parent_description

    project_id = template.get_effective_project_id()
    if project_id:
        task_params["project_id"] = project_id

    task_count = 0

    if dry_run:
        import random

        logger.debug("Dry run: parent task: '%s'", parent_title)
        if parent_description:
            logger.debug("Dry run: description: %s", parent_description)
        if project_id:
            logger.debug("Dry run: project ID: %s", project_id)
        parent_todo_id = f"dry_run_{random.randint(1000, 9999)}"
        task_count += 1
    else:
        try:
            logger.info("Creating parent task: '%s'", parent_title)
            todoist_parent = api.add_task(**task_params)
            parent_todo_id = todoist_parent.id
            logger.info("Parent task created: todo_id=%s", parent_todo_id)
        except Exception:
            logger.exception("Failed to create parent task: '%s'", parent_title)
            raise
        task_count += 1

    # Save the parent task instance with external ID
    parent_task_instance.todo_id = parent_todo_id
    if not dry_run:
        parent_task_instance.save()

    # Create child tasks from template
    top_level_tasks = template.template_tasks.filter(parent__isnull=True).order_by("order", "pk")
    for template_task in top_level_tasks:
        task_count += _create_task_from_template_task(
            api,
            template_task,
            token_values,
            parent_todo_id=parent_todo_id,
            parent_task_record=None,
            dry_run=dry_run,
        )

    logger.info(
        "Task group complete: template='%s', total_tasks=%d",
        template.title,
        task_count,
    )

    if dry_run:
        logger.debug("Dry run: total tasks: %d", task_count)

    return {
        "parent_task_instance": parent_task_instance,
        "task_count": task_count,
    }


def _create_task_from_template_task(
    api,
    template_task,
    token_values,
    parent_todo_id=None,
    parent_task_record=None,
    dry_run=False,
):
    """Create a Todoist task from a TemplateTask instance, then recurse into subtasks.

    Args:
        api: TodoistAPI instance (can be None if dry_run=True)
        template_task: TemplateTask model instance
        token_values: Dict of token replacements
        parent_todo_id: External parent task ID
        parent_task_record: Parent Task instance, or None for top-level tasks
        dry_run: If True, skip API calls and DB writes; log planned actions at DEBUG level

    Returns:
        Count of tasks created.
    """
    title = substitute_tokens(template_task.title, token_values)

    labels = []
    if template_task.labels:
        labels = [label.strip() for label in template_task.labels.split(",") if label.strip()]

    due_date_str = ""
    if template_task.due_date:
        due_date_str = template_task.due_date.isoformat()

    task_params = {"content": title}
    if labels:
        task_params["labels"] = labels
    # if due_date_str:
    task_params["due_date"] = template_task.due_date
    if parent_todo_id:
        task_params["parent_id"] = parent_todo_id

    count = 0

    if dry_run:
        import random

        logger.debug("Dry run: task: '%s'", title)
        if labels:
            logger.debug("Dry run: labels: %s", ", ".join(labels))
        created_todo_id = f"dry_run_{random.randint(1000, 9999)}"
        count += 1
    else:
        try:
            logger.info("Creating subtask: '%s' (parent=%s)", title, parent_todo_id)
            created_task = api.add_task(**task_params)
            created_todo_id = created_task.id
            logger.info("Subtask created: '%s', todo_id=%s", title, created_todo_id)
        except Exception:
            logger.exception("Failed to create subtask: '%s'", title)
            raise
        count += 1

    # Create Task record (parent_task links to either the parent Task or None for top-level)
    task_kwargs = {
        "parent_task": parent_task_record,
        "todo_id": created_todo_id,
        "title": title,
    }
    if due_date_str:
        task_kwargs["due_date"] = date.fromisoformat(due_date_str)

    task_record = None
    if not dry_run:
        task_record = Task.objects.create(**task_kwargs)

    # Recurse into subtasks
    for child in template_task.subtasks.order_by("order", "pk"):
        count += _create_task_from_template_task(
            api,
            child,
            token_values,
            parent_todo_id=created_todo_id,
            parent_task_record=task_record if not dry_run else None,
            dry_run=dry_run,
        )

    return count


def _verify_webhook_signature(request):
    """Verify the HMAC-SHA256 signature from Todoist.

    Returns True if TODOIST_WEBHOOK_SECRET is not configured (verification disabled).
    """
    secret = getattr(settings, "TODOIST_WEBHOOK_SECRET", None)
    if not secret:
        return True

    signature = request.headers.get("X-Todoist-Hmac-SHA256", "")
    digest = hmac.new(secret.encode(), request.body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(signature, expected)


def _move_task_by_label(task, item):
    """Move the parent task to a section based on the child's label and the parent's label_section_map."""
    if not item.parent_id:
        return

    try:
        parent = Task.objects.get(todo_id=item.parent_id)
    except Task.DoesNotExist:
        return

    try:
        base_parent = parent.baseparenttask
    except BaseParentTask.DoesNotExist:
        return

    if not base_parent.template:
        return

    model_class = base_parent.template.get_parent_task_model()
    if not model_class:
        return

    label_section_map = getattr(model_class, "label_section_map", {})
    if not label_section_map:
        return

    for label in item.labels:
        section_id = label_section_map.get(label)
        if section_id:
            api = get_api_client()
            if api:
                api.move_task(task_id=item.parent_id, section_id=section_id)
                logger.info(
                    "Moved parent task '%s' (%s) to section %s (child label: %s)",
                    parent.title,
                    item.parent_id,
                    section_id,
                    label,
                )
            return


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
    logger.info("Webhook received: %s for item '%s' (%s)", event, item.content, item.id)

    try:
        task = Task.objects.get(todo_id=item.id)
    except Task.DoesNotExist:
        logger.info(
            "Webhook %s: item '%s' (%s) not tracked, ignoring",
            event,
            item.content,
            item.id,
        )
        return HttpResponse(status=200)

    update_fields = []

    if event in (WebhookEventType.ITEM_COMPLETED, WebhookEventType.ITEM_DELETED):
        task.completed = True
        update_fields.append("completed")

        if event == WebhookEventType.ITEM_COMPLETED and item.labels:
            _move_task_by_label(task, item)

    elif event == WebhookEventType.ITEM_UNCOMPLETED:
        task.completed = False
        update_fields.append("completed")
    elif event in (WebhookEventType.ITEM_UPDATED, WebhookEventType.ITEM_ADDED):
        if item.checked != task.completed:
            task.completed = item.checked
            update_fields.append("completed")

        # Sync due_date from Todoist's due.date
        new_due = date.fromisoformat(item.due.date[:10]) if item.due else None
        if new_due != task.due_date:
            task.due_date = new_due
            update_fields.append("due_date")

    # Sync section changes for any event that carries section_id
    if item.section_id is not None and item.section_id != task.todo_section_id:
        task.todo_section_id = item.section_id
        update_fields.append("todo_section_id")

    if update_fields:
        task.save(update_fields=update_fields)
        logger.info(
            "Webhook %s: updated task '%s' (%s) (fields: %s)",
            event,
            item.content,
            item.id,
            update_fields,
        )
    else:
        logger.debug("Webhook %s: no changes for task '%s' (%s)", event, item.content, item.id)

    return HttpResponse(status=200)
