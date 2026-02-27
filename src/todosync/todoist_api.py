"""Todoist-specific API integration.

All direct interaction with the Todoist API lives here. If swapping to a
different task-management backend, this module is what gets replaced.
"""

import base64
import hashlib
import hmac
import logging
from datetime import date

import requests.exceptions
import stamina
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


def _is_retryable_request_error(exc: Exception) -> bool:
    if isinstance(exc, requests.exceptions.HTTPError):
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    return isinstance(
        exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)
    )


def get_api_client():
    """Return a configured TodoistAPI client, or None if no token is set."""
    api_token = getattr(settings, "TODOIST_API_TOKEN", None)
    if not api_token:
        return None
    return TodoistAPI(api_token)


def _add_todoist_task(api, task_params, label):
    """Call api.add_task with retry/error handling. Returns the created task's id."""
    try:
        logger.info("Creating Todoist task: %s", label)
        for attempt in stamina.retry_context(on=_is_retryable_request_error):
            with attempt:
                created = api.add_task(**task_params)
        logger.info("Todoist task created: todo_id=%s (%s)", created.id, label)
        return created.id
    except Exception:
        logger.exception("Failed to create Todoist task: %s", label)
        raise


def create_tasks_from_template(
    api, template, token_values, form_description="", dry_run=False, django_only=False
):
    """Create Todoist tasks from template and persist tracking records.

    Args:
        api: TodoistAPI instance (can be None if dry_run=True or django_only=True)
        template: BaseTaskGroupTemplate instance
        token_values: Dict of token replacements (field_name -> value)
        form_description: Optional description from the creation form
        dry_run: If True, skip API calls and DB writes; log planned actions at DEBUG level
        django_only: If True, skip Todoist API calls but still persist Django records

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
    elif django_only:
        logger.info("django_only: skipping Todoist creation for parent task '%s'", parent_title)
        parent_todo_id = ""
        task_count += 1
    else:
        parent_todo_id = _add_todoist_task(api, task_params, f"parent '{parent_title}'")
        task_count += 1

    # Save the parent task instance with external ID
    parent_task_instance.todo_id = parent_todo_id
    if not dry_run:
        parent_task_instance.save()

    # Create child tasks from template (flat — no subtask nesting).
    # The map accumulates template_task.pk → created Task so depends_on can be resolved.
    template_to_task_map = {}  # {template_task.pk: created Task}
    for template_task in template.template_tasks.order_by("order", "pk"):
        task_count += _create_task_from_template_task(
            api,
            template_task,
            token_values,
            parent_todo_id=parent_todo_id,
            parent_task_instance=parent_task_instance if not dry_run else None,
            dry_run=dry_run,
            template_to_task_map=template_to_task_map,
            django_only=django_only,
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
    parent_task_instance=None,
    dry_run=False,
    template_to_task_map=None,
    django_only=False,
):
    """Create a Todoist task from a TemplateTask instance.

    Args:
        api: TodoistAPI instance (can be None if dry_run=True or django_only=True)
        template_task: TemplateTask model instance
        token_values: Dict of token replacements
        parent_todo_id: External parent task ID (for Todoist nesting)
        parent_task_instance: BaseParentTask instance that owns this task
        dry_run: If True, skip API calls and DB writes; log planned actions at DEBUG level
        template_to_task_map: Mutable dict {template_task.pk: Task} for resolving depends_on
        django_only: If True, skip Todoist API call but still persist the Django Task record

    Returns:
        Count of tasks created (always 1).
    """
    title = substitute_tokens(template_task.title, token_values)
    description = (
        substitute_tokens(template_task.description, token_values)
        if template_task.description
        else ""
    )

    labels = list(template_task.tags.names())

    due_date_str = ""
    if template_task.due_date:
        due_date_str = template_task.due_date.isoformat()

    task_params = {"content": title, "order": template_task.order}
    if description:
        task_params["description"] = description
    if labels:
        task_params["labels"] = labels
    task_params["due_date"] = template_task.due_date
    if parent_todo_id:
        task_params["parent_id"] = parent_todo_id

    if template_task.hide:
        hide_priority = getattr(settings, "TODOIST_HIDE_PRIORITY", None)
        hide_label = getattr(settings, "TODOIST_HIDE_LABEL", None)
        if hide_priority is not None:
            task_params["priority"] = int(hide_priority)
        if hide_label:
            task_params.setdefault("labels", [])
            if hide_label not in task_params["labels"]:
                task_params["labels"].append(hide_label)

    if dry_run:
        import random

        logger.debug("Dry run: task: '%s'", title)
        if labels:
            logger.debug("Dry run: labels: %s", ", ".join(task_params.get("labels", labels)))
        if template_task.hide:
            logger.debug(
                "Dry run: hide=True (priority=%s, label=%s)",
                task_params.get("priority"),
                getattr(settings, "TODOIST_HIDE_LABEL", None),
            )
        created_todo_id = f"dry_run_{random.randint(1000, 9999)}"
    elif django_only:
        logger.info("django_only: skipping Todoist creation for task '%s'", title)
        created_todo_id = ""
    else:
        created_todo_id = _add_todoist_task(
            api, task_params, f"child '{title}' (parent={parent_todo_id})"
        )

    # Resolve depends_on: map the source TemplateTask dependency to the already-created Task.
    depends_on_task = None
    if template_task.depends_on_id and template_to_task_map:
        depends_on_task = template_to_task_map.get(template_task.depends_on_id)

    task_kwargs = {
        "parent_task": parent_task_instance,
        "template_task": template_task,
        "todo_id": created_todo_id,
        "title": title,
        "description": description,
        "depends_on": depends_on_task,
        "hide": template_task.hide,
    }
    if due_date_str:
        task_kwargs["due_date"] = date.fromisoformat(due_date_str)

    if not dry_run:
        task_record = Task.objects.create(**task_kwargs)
        task_record.tags.set(template_task.tags.all())
        if template_to_task_map is not None:
            # Register so later tasks in this run can depend on this one.
            template_to_task_map[template_task.pk] = task_record

    return 1


def create_todoist_task_for_django_task(api, task, project_id=None, parent_todo_id=None):
    """Create a Todoist task for a Django Task that has no todoist ID yet.

    Args:
        api: TodoistAPI instance
        task: Task or BaseParentTask instance
        project_id: Todoist project ID. If omitted, attempts to resolve via
                    task.parent_task.template.get_effective_project_id().
        parent_todo_id: Todoist parent task ID for nesting.

    Returns:
        The new todo_id string, or None if the task already had one.
    """
    if task.todo_id:
        logger.info(
            "Task '%s' already has todo_id=%s, skipping", task.title, task.todo_id
        )
        return None

    task_params = {"content": task.title}
    if task.description:
        task_params["description"] = task.description

    labels = list(task.tags.names())
    if labels:
        task_params["labels"] = labels

    resolved_project_id = project_id
    if not resolved_project_id and not parent_todo_id:
        try:
            resolved_project_id = task.parent_task.template.get_effective_project_id()
        except AttributeError:
            pass
    if resolved_project_id:
        task_params["project_id"] = resolved_project_id
    if parent_todo_id:
        task_params["parent_id"] = parent_todo_id

    if task.hide:
        hide_priority = getattr(settings, "TODOIST_HIDE_PRIORITY", "2")
        task_params["priority"] = int(hide_priority)
        hide_label = getattr(settings, "TODOIST_HIDE_LABEL", None)
        if hide_label:
            task_params.setdefault("labels", [])
            if hide_label not in task_params["labels"]:
                task_params["labels"].append(hide_label)

    todo_id = _add_todoist_task(api, task_params, task.title)
    task.todo_id = todo_id
    task.save()
    return todo_id


def update_todoist_task_hide(api, task):
    """Update a Todoist task's priority and labels to reflect the current hide state.

    hide=True  → TODOIST_HIDE_PRIORITY + TODOIST_HIDE_LABEL added to labels.
    hide=False → priority 1 (normal) + TODOIST_HIDE_LABEL removed from labels.
    """
    if not task.todo_id:
        return

    hide_priority = int(getattr(settings, "TODOIST_HIDE_PRIORITY", 2))
    hide_label = getattr(settings, "TODOIST_HIDE_LABEL", None)

    update_kwargs = {"priority": hide_priority if task.hide else 1}

    if hide_label is not None:
        labels = list(task.tags.names())
        if task.hide and hide_label not in labels:
            labels.append(hide_label)
        elif not task.hide and hide_label in labels:
            labels.remove(hide_label)
        update_kwargs["labels"] = labels

    try:
        logger.info(
            "Updating Todoist task hide state: todo_id=%s, hide=%s", task.todo_id, task.hide
        )
        for attempt in stamina.retry_context(on=_is_retryable_request_error):
            with attempt:
                api.update_task(task.todo_id, **update_kwargs)
        logger.info("Updated Todoist task hide state: todo_id=%s", task.todo_id)
    except Exception:
        logger.exception("Failed to update Todoist task hide state: %s", task.todo_id)
        raise


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
                for attempt in stamina.retry_context(on=_is_retryable_request_error):
                    with attempt:
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
        logger.debug(
            "Webhook %s: no changes for task '%s' (%s)", event, item.content, item.id
        )

    return HttpResponse(status=200)
