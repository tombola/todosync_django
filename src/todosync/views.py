import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import redirect, render

from .models import BaseTaskGroupTemplate
from .forms import BaseTaskGroupCreationForm
from .todoist_api import get_api_client, create_tasks_from_template

logger = logging.getLogger(__name__)


@staff_member_required
def create_task_group(request):
    """View for creating task groups from templates
    creates tasks *from* a template, not a new template itself.
    """

    template_id = request.GET.get("template_id") or request.POST.get("template_id")

    if request.method == "POST":
        form = BaseTaskGroupCreationForm(request.POST, template_id=template_id)

        if form.is_valid():
            template = form.cleaned_data["task_group_template"]
            token_values = form.get_token_values()
            form_description = form.cleaned_data.get("description", "")

            dry_run = getattr(settings, "DRY_RUN_TASK_CREATION", False)

            logger.info(
                "Task group creation requested: template='%s', tokens=%s",
                template.title,
                token_values,
            )

            try:
                if dry_run:
                    result = create_tasks_from_template(
                        None, template, token_values, form_description, dry_run=True
                    )
                    logger.info(
                        "Task group created (dry run): template='%s', task_count=%d",
                        template.title,
                        result["task_count"],
                    )
                    messages.success(
                        request, f"DRY RUN: Would create {result['task_count']} tasks"
                    )
                else:
                    api = get_api_client()
                    if not api:
                        logger.warning(
                            "Task creation failed: Todoist API token not configured"
                        )
                        messages.error(request, "Todoist API token not configured")
                        return redirect("todosync:create_task_group")

                    result = create_tasks_from_template(
                        api,
                        template,
                        token_values,
                        form_description,
                    )
                    logger.info(
                        "Task group created: template='%s', task_count=%d",
                        template.title,
                        result["task_count"],
                    )
                    messages.success(
                        request, f"Successfully created {result['task_count']} tasks"
                    )

                return redirect("todosync:create_task_group")

            except Exception as e:
                logger.exception(
                    "Task group creation failed: template='%s'", template.title
                )
                error_message = str(e)

                if "400 Client Error: Bad Request" in error_message:
                    project_id = template.get_effective_project_id()
                    if project_id:
                        messages.error(
                            request,
                            f'Invalid project ID: "{project_id}". '
                            'Please run "python manage.py list_todoist_projects" to see valid project IDs.',
                        )
                    else:
                        messages.error(
                            request,
                            "Invalid request to task API. Please check your task template configuration.",
                        )
                elif "401" in error_message or "Unauthorized" in error_message:
                    messages.error(
                        request,
                        "Task API authentication failed. Please check your API token in Settings.",
                    )
                elif "403" in error_message or "Forbidden" in error_message:
                    messages.error(
                        request,
                        "Permission denied. Your API token may not have access to this project.",
                    )
                else:
                    messages.error(request, f"Error creating tasks: {error_message}")

    else:
        form = BaseTaskGroupCreationForm(template_id=template_id)

    selected_template = None
    token_field_names = []
    parent_task_title_template = ""
    parent_task_description_template = ""
    if template_id:
        try:
            selected_template = BaseTaskGroupTemplate.objects.get(id=template_id)
            token_field_names = selected_template.get_token_field_names()
            parent_task_model = selected_template.get_parent_task_model()
            if parent_task_model:
                dummy = parent_task_model()
                for name in token_field_names:
                    setattr(dummy, name, "{" + name + "}")
                parent_task_title_template = dummy.get_parent_task_title()
                parent_task_description_template = dummy.get_description()
        except BaseTaskGroupTemplate.DoesNotExist:
            pass

    return render(
        request,
        "todosync/create_task_group.html",
        {
            "form": form,
            "template_id": template_id,
            "selected_template": selected_template,
            "token_field_names": token_field_names,
            "parent_task_title_template": parent_task_title_template,
            "parent_task_description_template": parent_task_description_template,
        },
    )
