#!/usr/bin/env python
"""Test script to debug Todoist API issues.

Uses TODOIST_TEST_API_TOKEN and TODOIST_TEST_PROJECT from environment.
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taskplanner.settings.dev")
import django

django.setup()

from todoist_api_python.api import TodoistAPI

API_TOKEN = os.getenv("TODOIST_TEST_API_TOKEN")
PROJECT_ID = os.getenv("TODOIST_TEST_PROJECT")


def get_api():
    """Return a configured TodoistAPI client using the test token."""
    if not API_TOKEN:
        print("ERROR: TODOIST_TEST_API_TOKEN not found in environment")
        sys.exit(1)
    return TodoistAPI(API_TOKEN)


def test_basic_task():
    """Test creating a basic task without any optional parameters"""
    api = get_api()

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


def test_task_with_project():
    """Test creating a task with project_id"""
    api = get_api()

    if not PROJECT_ID:
        print("\nTest 2: Skipped (TODOIST_TEST_PROJECT not set)")
        return None

    print(f"\nTest 2: Task with project_id: {PROJECT_ID}")
    try:
        task = api.add_task(content="Test task with project", project_id=PROJECT_ID)
        print(f"✓ Success! Task ID: {task.id}")
        return task
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback

        traceback.print_exc()
        return None


def test_task_with_parent(parent_id):
    """Test creating a child task with parent_id"""
    if not parent_id:
        print("\nTest 3: Skipped (no parent task)")
        return None

    api = get_api()

    print(f"\nTest 3: Child task with parent_id: {parent_id}")
    try:
        task = api.add_task(content="Test child task", parent_id=parent_id)
        print(f"✓ Success! Task ID: {task.id}")
        return task
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback

        traceback.print_exc()
        return None


def test_task_with_labels():
    """Test creating a task with labels"""
    api = get_api()

    print("\nTest 4: Task with labels")
    try:
        task = api.add_task(content="Test task with labels", labels=["test", "debug"])
        print(f"✓ Success! Task ID: {task.id}")
        return task
    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback

        traceback.print_exc()
        return None


def test_full_combination():
    """Test creating a task with project_id, description, and labels"""
    api = get_api()

    if not PROJECT_ID:
        print("\nTest 5: Skipped (TODOIST_TEST_PROJECT not set)")
        return None

    print("\nTest 5: Full combination (project_id + description + labels)")
    try:
        task = api.add_task(
            content="Test task with all parameters",
            description="This is a test description",
            project_id=PROJECT_ID,
            labels=["test", "debug"],
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
    api = get_api()

    print("\n" + "=" * 60)
    print("Cleaning up test tasks...")
    for tid in task_ids:
        if tid:
            try:
                api.delete_task(task_id=tid)
                print(f"✓ Deleted task {tid}")
            except Exception as e:
                print(f"✗ Failed to delete task {tid}: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("Todoist API Debug Test")
    print("=" * 60)

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

    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)
