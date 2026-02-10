import logging

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render

from .models import BaseTaskGroupTemplate
from .forms import BaseTaskGroupCreationForm
from .todoist_api import get_api_client, create_tasks_from_template

logger = logging.getLogger(__name__)


def create_task_group(request):
    """View for creating task groups from templates"""

    template_id = request.GET.get('template_id') or request.POST.get('template_id')
    site = request.site if hasattr(request, 'site') else None

    if site is None:
        from wagtail.models import Site
        site = Site.find_for_request(request)

    if request.method == 'POST':
        form = BaseTaskGroupCreationForm(request.POST, template_id=template_id, site=site)

        if form.is_valid():
            template = form.cleaned_data['task_group_template'].specific
            token_values = form.get_token_values()
            form_description = form.cleaned_data.get('description', '')

            debug_mode = getattr(settings, 'DEBUG_TASK_CREATION', False)

            try:
                if debug_mode:
                    result = create_tasks_from_template(
                        None, template, token_values, site, form_description, debug=True
                    )
                    messages.success(
                        request,
                        f'DEBUG MODE: Printed {result["task_count"]} tasks to console'
                    )
                else:
                    api = get_api_client()
                    if not api:
                        messages.error(request, 'Todoist API token not configured')
                        return redirect('todosync:create_task_group')

                    result = create_tasks_from_template(
                        api, template, token_values, site, form_description, debug=False
                    )
                    messages.success(
                        request,
                        f'Successfully created {result["task_count"]} tasks'
                    )

                return redirect('todosync:create_task_group')

            except Exception as e:
                error_message = str(e)

                if '400 Client Error: Bad Request' in error_message:
                    project_id = template.get_effective_project_id(site)
                    if project_id:
                        messages.error(
                            request,
                            f'Invalid project ID: "{project_id}". '
                            'Please run "python manage.py list_todoist_projects" to see valid project IDs.'
                        )
                    else:
                        messages.error(
                            request,
                            'Invalid request to task API. Please check your task template configuration.'
                        )
                elif '401' in error_message or 'Unauthorized' in error_message:
                    messages.error(
                        request,
                        'Task API authentication failed. Please check your API token in Settings.'
                    )
                elif '403' in error_message or 'Forbidden' in error_message:
                    messages.error(
                        request,
                        'Permission denied. Your API token may not have access to this project.'
                    )
                else:
                    messages.error(request, f'Error creating tasks: {error_message}')

    else:
        form = BaseTaskGroupCreationForm(template_id=template_id, site=site)

    selected_template = None
    if template_id:
        try:
            selected_template = BaseTaskGroupTemplate.objects.get(id=template_id).specific
        except BaseTaskGroupTemplate.DoesNotExist:
            pass

    return render(request, 'todosync/create_task_group.html', {
        'form': form,
        'template_id': template_id,
        'selected_template': selected_template,
    })
