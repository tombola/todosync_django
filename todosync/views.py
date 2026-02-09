from django.shortcuts import render, redirect
from django.contrib import messages
from django.conf import settings
from todoist_api_python.api import TodoistAPI
from wagtail.models import Site

from .models import BaseTaskGroupTemplate, TaskSyncSettings, TaskGroup
from .forms import BaseTaskGroupCreationForm
from .utils import substitute_tokens
import sys


def create_task_group(request):
    """View for creating task groups from templates"""

    template_id = request.GET.get('template_id') or request.POST.get('template_id')

    # Get the site for accessing settings
    site = Site.find_for_request(request)

    if request.method == 'POST':
        form = BaseTaskGroupCreationForm(request.POST, template_id=template_id, site=site)

        if form.is_valid():
            template = form.cleaned_data['task_group_template']
            token_values = form.get_token_values()
            form_description = form.cleaned_data.get('description', '')

            # Check debug mode from Django settings
            debug_mode = getattr(settings, 'DEBUG_TASK_CREATION', False)

            # Create tasks via Todoist API or debug print
            try:
                if debug_mode:
                    # Debug mode: print to console instead of posting
                    created_tasks = create_tasks_from_template(None, template, token_values, site, form_description, debug=True)
                    messages.success(request, f'DEBUG MODE: Printed {len(created_tasks)} tasks to console')
                else:
                    # Normal mode: post to Todoist API
                    api_token = getattr(settings, 'TODOIST_API_TOKEN', None)
                    if not api_token:
                        messages.error(request, 'Todoist API token not configured')
                        return redirect('todosync:create_task_group')

                    api = TodoistAPI(api_token)
                    created_tasks = create_tasks_from_template(api, template, token_values, site, form_description, debug=False)
                    messages.success(request, f'Successfully created {len(created_tasks)} tasks')

                return redirect('todosync:create_task_group')

            except Exception as e:
                error_message = str(e)

                # Provide more helpful error messages for common issues
                if '400 Client Error: Bad Request' in error_message:
                    sync_settings = TaskSyncSettings.for_site(site)
                    if sync_settings.todoist_project_id:
                        messages.error(
                            request,
                            f'Invalid Todoist project ID: "{sync_settings.todoist_project_id}". '
                            'Please run "python manage.py list_todoist_projects" to see valid project IDs, '
                            'then update the project ID in Settings → Task Sync Settings.'
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

    # Get the selected template for displaying task structure
    selected_template = None
    if template_id:
        try:
            selected_template = BaseTaskGroupTemplate.objects.get(id=template_id)
        except BaseTaskGroupTemplate.DoesNotExist:
            pass

    # Get sync settings for displaying descriptions
    sync_settings = TaskSyncSettings.for_site(site)

    return render(request, 'todosync/create_task_group.html', {
        'form': form,
        'template_id': template_id,
        'selected_template': selected_template,
        'sync_settings': sync_settings,
    })


def create_tasks_from_template(api, template, token_values, site, form_description='', debug=False):
    """Create Todoist tasks from template with token substitution

    Args:
        api: TodoistAPI instance (can be None if debug=True)
        template: BaseTaskGroupTemplate instance
        token_values: Dict of token replacements
        site: Wagtail Site instance for accessing settings
        form_description: Optional description from the creation form
        debug: If True, print debug info instead of posting to API
    """
    created_tasks = []

    if debug:
        print("\n" + "="*80, file=sys.stderr)
        print(f"DEBUG: Creating tasks from template: {template.title}", file=sys.stderr)
        print(f"DEBUG: Token values: {token_values}", file=sys.stderr)
        print("="*80 + "\n", file=sys.stderr)

    # Get parent task title from settings, or use template title as fallback
    sync_settings = TaskSyncSettings.for_site(site)
    if sync_settings.parent_task_title:
        parent_title = sync_settings.parent_task_title
    else:
        parent_title = template.title

    # Substitute tokens in parent title
    parent_title = substitute_tokens(parent_title, token_values)

    # Build parent task description from settings, template, and form descriptions
    description_parts = []

    # Add site-wide description first (if exists)
    if sync_settings.description:
        site_description = substitute_tokens(sync_settings.description, token_values)
        description_parts.append(site_description)

    # Add template description second (if exists)
    if template.description:
        template_description = substitute_tokens(template.description, token_values)
        description_parts.append(template_description)

    # Add form description third (if exists)
    if form_description:
        form_desc = substitute_tokens(form_description, token_values)
        description_parts.append(form_desc)

    # Combine descriptions with double newline separator
    parent_description = '\n\n'.join(description_parts) if description_parts else ''

    # Create parent task from template page
    task_params = {
        'content': parent_title,
    }

    # Only add description if there is one
    if parent_description:
        task_params['description'] = parent_description

    # Add project_id if specified in settings
    if sync_settings.todoist_project_id:
        task_params['project_id'] = sync_settings.todoist_project_id

    if debug:
        # Debug mode: print parent task info
        print(f"Parent Task: {parent_title}", file=sys.stderr)
        if parent_description:
            print(f"  Description: {parent_description}", file=sys.stderr)
        if sync_settings.todoist_project_id:
            print(f"  Project ID: {sync_settings.todoist_project_id}", file=sys.stderr)

        # Create a mock task object with just an id
        class MockTask:
            def __init__(self):
                import random
                self.id = f"debug_{random.randint(1000, 9999)}"

        parent_task = MockTask()
    else:
        # Normal mode: create parent task via API
        try:
            print(f"DEBUG: Creating parent task with params: {task_params}", file=sys.stderr)
            parent_task = api.add_task(**task_params)
            print(f"DEBUG: Parent task created successfully: {parent_task.id}", file=sys.stderr)
        except Exception as e:
            print(f"ERROR: Failed to create parent task: {str(e)}", file=sys.stderr)
            print(f"ERROR: Task params were: {task_params}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            raise

    created_tasks.append(parent_task)

    # Create all template tasks as subtasks of the parent
    for task_data in template.tasks:
        if task_data.block_type == 'task':
            task_block = task_data.value
            created_task = create_task_recursive(api, task_block, token_values, parent_id=parent_task.id, debug=debug, indent=1)
            if created_task:
                created_tasks.append(created_task)

    if debug:
        print("\n" + "="*80, file=sys.stderr)
        print(f"DEBUG: Total tasks created: {len(created_tasks)}", file=sys.stderr)
        print("="*80 + "\n", file=sys.stderr)
    else:
        # Create TaskGroup record to track this creation
        TaskGroup.objects.create(
            template=template,
            token_values=token_values,
            parent_task_id=parent_task.id
        )

    return created_tasks


def create_task_recursive(api, task_block, token_values, parent_id=None, debug=False, indent=0):
    """Recursively create a task and its subtasks

    Args:
        api: TodoistAPI instance (can be None if debug=True)
        task_block: Task block data
        token_values: Dict of token replacements
        parent_id: Parent task ID (None for top-level tasks)
        debug: If True, print debug info instead of posting to API
        indent: Indentation level for debug output
    """

    # Substitute tokens in title
    title = substitute_tokens(task_block['title'], token_values)

    # Parse labels
    labels = []
    if task_block.get('labels'):
        labels = [label.strip() for label in task_block['labels'].split(',') if label.strip()]

    # Create task via API or print debug info
    task_params = {
        'content': title,
    }

    # Only add labels if there are any
    if labels:
        task_params['labels'] = labels

    # Only add parent_id if it exists
    if parent_id:
        task_params['parent_id'] = parent_id

    if debug:
        # Debug mode: print task info
        indent_str = "  " * indent
        print(f"{indent_str}Task: {title}", file=sys.stderr)
        if labels:
            print(f"{indent_str}  Labels: {', '.join(labels)}", file=sys.stderr)
        if parent_id:
            print(f"{indent_str}  Parent ID: {parent_id}", file=sys.stderr)

        # Create a mock task object with just an id
        class MockTask:
            def __init__(self):
                import random
                self.id = f"debug_{random.randint(1000, 9999)}"

        created_task = MockTask()
    else:
        # Normal mode: create task via API
        try:
            print(f"DEBUG: Creating task with params: {task_params}", file=sys.stderr)
            created_task = api.add_task(**task_params)
            print(f"DEBUG: Task created successfully: {created_task.id}", file=sys.stderr)
        except Exception as e:
            print(f"ERROR: Failed to create task: {str(e)}", file=sys.stderr)
            print(f"ERROR: Task params were: {task_params}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            raise

    # Create subtasks if they exist (ListBlock returns a list of dicts)
    if task_block.get('subtasks'):
        for subtask_data in task_block['subtasks']:
            # Subtasks are plain dicts from ListBlock
            create_task_recursive(api, subtask_data, token_values, parent_id=created_task.id, debug=debug, indent=indent+1)

    return created_task
