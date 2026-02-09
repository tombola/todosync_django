#!/usr/bin/env python
"""Test script to debug Todoist API issues"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'taskplanner.settings.dev')
import django
django.setup()

from todoist_api_python.api import TodoistAPI
from tasks.models import TaskPlannerSettings
from wagtail.models import Site

def test_basic_task():
    """Test creating a basic task without any optional parameters"""
    api_token = os.getenv('TODOIST_API_TOKEN')
    if not api_token:
        print("ERROR: TODOIST_API_TOKEN not found in environment")
        sys.exit(1)

    api = TodoistAPI(api_token)

    print("Test 1: Basic task (content only)")
    try:
        task = api.add_task(content="Test task from debug script")
        print(f"✓ Success! Task ID: {task.id}")
        return task
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_task_with_project(basic_task_id=None):
    """Test creating a task with project_id"""
    api_token = os.getenv('TODOIST_API_TOKEN')
    api = TodoistAPI(api_token)

    # Get project_id from settings
    site = Site.objects.get(is_default_site=True)
    settings = TaskPlannerSettings.for_site(site)

    if not settings.todoist_project_id:
        print("\nTest 2: Skipped (no project_id configured in settings)")
        return None

    print(f"\nTest 2: Task with project_id: {settings.todoist_project_id}")
    try:
        task = api.add_task(
            content="Test task with project",
            project_id=settings.todoist_project_id
        )
        print(f"✓ Success! Task ID: {task.id}")
        return task
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_task_with_parent(parent_id):
    """Test creating a subtask with parent_id"""
    if not parent_id:
        print("\nTest 3: Skipped (no parent task)")
        return None

    api_token = os.getenv('TODOIST_API_TOKEN')
    api = TodoistAPI(api_token)

    print(f"\nTest 3: Subtask with parent_id: {parent_id}")
    try:
        task = api.add_task(
            content="Test subtask",
            parent_id=parent_id
        )
        print(f"✓ Success! Task ID: {task.id}")
        return task
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_task_with_labels():
    """Test creating a task with labels"""
    api_token = os.getenv('TODOIST_API_TOKEN')
    api = TodoistAPI(api_token)

    print("\nTest 4: Task with labels")
    try:
        task = api.add_task(
            content="Test task with labels",
            labels=["test", "debug"]
        )
        print(f"✓ Success! Task ID: {task.id}")
        return task
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_full_combination():
    """Test creating a task with project_id, description, and labels"""
    api_token = os.getenv('TODOIST_API_TOKEN')
    api = TodoistAPI(api_token)

    # Get project_id from settings
    site = Site.objects.get(is_default_site=True)
    settings = TaskPlannerSettings.for_site(site)

    if not settings.todoist_project_id:
        print("\nTest 5: Skipped (no project_id configured)")
        return None

    print(f"\nTest 5: Full combination (project_id + description + labels)")
    try:
        task = api.add_task(
            content="Test task with all parameters",
            description="This is a test description",
            project_id=settings.todoist_project_id,
            labels=["test", "debug"]
        )
        print(f"✓ Success! Task ID: {task.id}")
        return task
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def cleanup_tasks(task_ids):
    """Delete test tasks"""
    api_token = os.getenv('TODOIST_API_TOKEN')
    api = TodoistAPI(api_token)

    print("\n" + "="*60)
    print("Cleaning up test tasks...")
    for task_id in task_ids:
        if task_id:
            try:
                api.delete_task(task_id)
                print(f"✓ Deleted task {task_id}")
            except Exception as e:
                print(f"✗ Failed to delete task {task_id}: {e}")

if __name__ == "__main__":
    print("="*60)
    print("Todoist API Debug Test")
    print("="*60)

    task_ids = []

    # Run tests
    basic_task = test_basic_task()
    if basic_task:
        task_ids.append(basic_task.id)

    project_task = test_task_with_project()
    if project_task:
        task_ids.append(project_task.id)

    subtask = test_task_with_parent(basic_task.id if basic_task else None)
    if subtask:
        task_ids.append(subtask.id)

    label_task = test_task_with_labels()
    if label_task:
        task_ids.append(label_task.id)

    full_task = test_full_combination()
    if full_task:
        task_ids.append(full_task.id)

    # Cleanup
    cleanup_tasks(task_ids)

    print("\n" + "="*60)
    print("Test complete!")
    print("="*60)
