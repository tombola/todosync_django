import sys

from django.shortcuts import render, redirect
from django.contrib import messages
from django.conf import settings
from todoist_api_python.api import TodoistAPI
from wagtail.models import Site

from .models import BaseTaskGroupTemplate, Task
from .forms import BaseTaskGroupCreationForm
from .utils import substitute_tokens


def create_task_group(request):
    """View for creating task groups from templates"""

    template_id = request.GET.get('template_id') or request.POST.get('template_id')
    site = Site.find_for_request(request)

    if request.method == 'POST':
        form = BaseTaskGroupCreationForm(request.POST, template_id=template_id, site=site)

        if form.is_valid():
            template = form.cleaned_data['task_group_template']
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
                    api_token = getattr(settings, 'TODOIST_API_TOKEN', None)
                    if not api_token:
                        messages.error(request, 'Todoist API token not configured')
                        return redirect('todosync:create_task_group')

                    api = TodoistAPI(api_token)
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
                            f'Invalid Todoist project ID: "{project_id}". '
                            'Please run "python manage.py list_todoist_projects" to see valid project IDs.'
                        )
                    else:
                        messages.error(
                            request,
                            'Invalid request to Todoist API. Please check your task template configuration.'
                        )
                elif '401' in error_message or 'Unauthorized' in error_message:
                    messages.error(
                        request,
                        'Todoist API authentication failed. Please check your API token in Settings.'
                    )
                elif '403' in error_message or 'Forbidden' in error_message:
                    messages.error(
                        request,
                        'Permission denied. Your Todoist API token may not have access to this project.'
                    )
                else:
                    messages.error(request, f'Error creating tasks: {error_message}')

    else:
        form = BaseTaskGroupCreationForm(template_id=template_id, site=site)

    selected_template = None
    if template_id:
        try:
            selected_template = BaseTaskGroupTemplate.objects.get(id=template_id)
        except BaseTaskGroupTemplate.DoesNotExist:
            pass

    return render(request, 'todosync/create_task_group.html', {
        'form': form,
        'template_id': template_id,
        'selected_template': selected_template,
    })


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
        todoist_parent_id = f"debug_{random.randint(1000, 9999)}"
        task_count += 1
    else:
        try:
            print(f"DEBUG: Creating parent task with params: {task_params}", file=sys.stderr)
            todoist_parent = api.add_task(**task_params)
            todoist_parent_id = todoist_parent.id
            print(f"DEBUG: Parent task created successfully: {todoist_parent_id}", file=sys.stderr)
        except Exception as e:
            print(f"ERROR: Failed to create parent task: {e}", file=sys.stderr)
            print(f"ERROR: Task params were: {task_params}", file=sys.stderr)
            raise
        task_count += 1

    # Save the parent task instance with Todoist ID
    parent_task_instance.todoist_id = todoist_parent_id
    if not debug:
        parent_task_instance.save()

    # Create child tasks from template
    for task_data in template.tasks:
        if task_data.block_type == 'task':
            task_block = task_data.value
            task_count += _create_task_recursive(
                api, task_block, token_values,
                parent_todoist_id=todoist_parent_id,
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


def _create_task_recursive(api, task_block, token_values, parent_todoist_id=None,
                           parent_task_record=None, debug=False, indent=0):
    """Recursively create a task and its subtasks.

    Args:
        api: TodoistAPI instance (can be None if debug=True)
        task_block: Task block data from StreamField
        token_values: Dict of token replacements
        parent_todoist_id: Todoist parent task ID
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
    if parent_todoist_id:
        task_params['parent_id'] = parent_todoist_id

    count = 0

    if debug:
        import random
        indent_str = "  " * indent
        print(f"{indent_str}Task: {title}", file=sys.stderr)
        if labels:
            print(f"{indent_str}  Labels: {', '.join(labels)}", file=sys.stderr)
        created_todoist_id = f"debug_{random.randint(1000, 9999)}"
        count += 1
    else:
        try:
            print(f"DEBUG: Creating task with params: {task_params}", file=sys.stderr)
            created_task = api.add_task(**task_params)
            created_todoist_id = created_task.id
            print(f"DEBUG: Task created successfully: {created_todoist_id}", file=sys.stderr)
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
            todoist_id=created_todoist_id,
            title=title,
        )

    # Recurse into subtasks
    if task_block.get('subtasks'):
        for subtask_data in task_block['subtasks']:
            count += _create_task_recursive(
                api, subtask_data, token_values,
                parent_todoist_id=created_todoist_id,
                parent_task_record=task_record if not debug else None,
                debug=debug,
                indent=indent + 1,
            )

    return count
