import base64
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client
from django.urls import reverse

from todosync.models import Task

FIXTURES_DIR = Path(__file__).parent / "fixtures"

WEBHOOK_URL = reverse("todosync:todoist_webhook")


def _load_fixture(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


def _sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


@pytest.fixture
def tracked_task(db):
    """A Task record that matches the todo_id used in fixtures."""
    return Task.objects.create(
        todo_id="ABC123",
        title="Sow tomatoes",
        todo_section_id="3Ty8VQXxpwv28PK3",
        completed=False,
    )


@pytest.fixture
def client():
    return Client()


# -- request method / payload validation --


def test_rejects_get(client):
    response = client.get(WEBHOOK_URL)
    assert response.status_code == 405


def test_rejects_invalid_json(client):
    response = client.post(
        WEBHOOK_URL,
        data=b"not json",
        content_type="application/json",
    )
    assert response.status_code == 400


def test_rejects_unknown_event_type(client):
    payload = json.dumps(
        {
            "event_name": "note:added",
            "event_data": {"id": "x", "content": "x"},
        }
    )
    response = client.post(
        WEBHOOK_URL,
        data=payload,
        content_type="application/json",
    )
    assert response.status_code == 400


# -- untracked task --


def test_untracked_task_returns_200(client, db):
    body = _load_fixture("item_completed.json")
    response = client.post(WEBHOOK_URL, data=body, content_type="application/json")
    assert response.status_code == 200


# -- item:completed --


def test_item_completed(client, tracked_task):
    body = _load_fixture("item_completed.json")
    response = client.post(WEBHOOK_URL, data=body, content_type="application/json")

    assert response.status_code == 200
    tracked_task.refresh_from_db()
    assert tracked_task.completed is True


# -- item:uncompleted --


def test_item_uncompleted(client, db):
    task = Task.objects.create(
        todo_id="ABC123",
        title="Sow tomatoes",
        todo_section_id="3Ty8VQXxpwv28PK3",
        completed=True,
    )
    body = _load_fixture("item_uncompleted.json")
    response = client.post(WEBHOOK_URL, data=body, content_type="application/json")

    assert response.status_code == 200
    task.refresh_from_db()
    assert task.completed is False


# -- item:deleted --


def test_item_deleted(client, tracked_task):
    body = _load_fixture("item_deleted.json")
    response = client.post(WEBHOOK_URL, data=body, content_type="application/json")

    assert response.status_code == 200
    tracked_task.refresh_from_db()
    assert tracked_task.completed is True


# -- item:updated --


def test_item_updated_section_change(client, tracked_task):
    body = _load_fixture("item_updated_section.json")
    response = client.post(WEBHOOK_URL, data=body, content_type="application/json")

    assert response.status_code == 200
    tracked_task.refresh_from_db()
    assert tracked_task.todo_section_id == "9Zz2NEW_SECTION"
    assert tracked_task.completed is False  # unchanged


def test_item_updated_no_change(client, tracked_task):
    """Webhook with matching state produces no DB write."""
    body = _load_fixture("item_added.json")
    response = client.post(WEBHOOK_URL, data=body, content_type="application/json")

    assert response.status_code == 200
    tracked_task.refresh_from_db()
    assert tracked_task.completed is False
    assert tracked_task.todo_section_id == "3Ty8VQXxpwv28PK3"


# -- item:added with checked=true --


def test_item_added_already_checked(client, tracked_task):
    """item:added with checked=true syncs completed status."""
    fixture = json.loads(_load_fixture("item_added.json"))
    fixture["event_data"]["checked"] = True
    body = json.dumps(fixture).encode()

    response = client.post(WEBHOOK_URL, data=body, content_type="application/json")

    assert response.status_code == 200
    tracked_task.refresh_from_db()
    assert tracked_task.completed is True


# -- HMAC signature verification --


def test_hmac_valid_signature(client, tracked_task, settings):
    settings.TODOIST_WEBHOOK_SECRET = "test-secret"
    body = _load_fixture("item_completed.json")
    sig = _sign(body, "test-secret")

    response = client.post(
        WEBHOOK_URL,
        data=body,
        content_type="application/json",
        HTTP_X_TODOIST_HMAC_SHA256=sig,
    )
    assert response.status_code == 200
    tracked_task.refresh_from_db()
    assert tracked_task.completed is True


def test_hmac_invalid_signature(client, tracked_task, settings):
    settings.TODOIST_WEBHOOK_SECRET = "test-secret"
    body = _load_fixture("item_completed.json")

    response = client.post(
        WEBHOOK_URL,
        data=body,
        content_type="application/json",
        HTTP_X_TODOIST_HMAC_SHA256="bad-signature",
    )
    assert response.status_code == 403
    tracked_task.refresh_from_db()
    assert tracked_task.completed is False  # unchanged


def test_hmac_skipped_when_no_secret(client, tracked_task, settings):
    settings.TODOIST_WEBHOOK_SECRET = ""
    body = _load_fixture("item_completed.json")

    response = client.post(WEBHOOK_URL, data=body, content_type="application/json")
    assert response.status_code == 200
    tracked_task.refresh_from_db()
    assert tracked_task.completed is True


# -- label-based section move on completion --


@pytest.fixture
def crop_task_with_child(db):
    """A CropTask parent with a child Task matching the fixture todo_id."""
    from tasks.models import CropTask, CropTaskGroupTemplate

    template = CropTaskGroupTemplate.objects.create(title="Sow template")
    parent = CropTask.objects.create(
        template=template,
        title="TOM-001 - Tomato",
        todo_id="PARENT123",
        crop="Tomato",
        sku="TOM-001",
        variety_name="Roma",
        bed="B1",
    )
    child = Task.objects.create(
        todo_id="ABC123",
        title="Sow tomatoes",
        completed=False,
    )
    return parent, child


@pytest.fixture
def template_with_tasks(db):
    """A CropTaskGroupTemplate with two TemplateTask children."""
    from tasks.models import CropTaskGroupTemplate
    from todosync.models import TemplateTask

    template = CropTaskGroupTemplate.objects.create(
        title="Sow template", project_id="proj123"
    )
    TemplateTask.objects.create(template=template, title="Sow {SKU}", order=1)
    TemplateTask.objects.create(template=template, title="Water {SKU}", order=2)
    return template


def test_django_only_then_push_to_todoist(db, template_with_tasks):
    """django_only=True creates Django records without Todoist calls;
    create_todoist_task_for_django_task then pushes each to Todoist."""
    from todosync.models import Task
    from todosync.todoist_api import (
        create_tasks_from_template,
        create_todoist_task_for_django_task,
    )

    mock_api = MagicMock()
    token_values = {
        "sku": "TOM-001",
        "crop": "Tomato",
        "variety_name": "Roma",
        "bed": "B1",
        "seed_source": "supplier",
        "spacing": "30cm",
    }

    # Step 1: create django records only — no Todoist calls
    result = create_tasks_from_template(
        mock_api, template_with_tasks, token_values, django_only=True
    )
    mock_api.add_task.assert_not_called()

    parent = result["parent_task_instance"]
    assert parent.pk is not None
    assert parent.todo_id == ""

    child_tasks = list(Task.objects.filter(parent_task=parent))
    assert len(child_tasks) == 2
    assert all(t.todo_id == "" for t in child_tasks)

    # Step 2: push each task to Todoist
    mock_api.add_task.side_effect = [
        MagicMock(id="todo_parent"),
        MagicMock(id="todo_child1"),
        MagicMock(id="todo_child2"),
    ]

    returned_id = create_todoist_task_for_django_task(mock_api, parent)
    assert returned_id == "todo_parent"
    parent.refresh_from_db()
    assert parent.todo_id == "todo_parent"

    for task in child_tasks:
        create_todoist_task_for_django_task(mock_api, task)

    assert mock_api.add_task.call_count == 3

    for task in child_tasks:
        task.refresh_from_db()
        assert task.todo_id != ""

    # Step 3: calling again on a task that already has a todo_id is a no-op
    result2 = create_todoist_task_for_django_task(mock_api, parent)
    assert result2 is None
    assert mock_api.add_task.call_count == 3  # unchanged


@pytest.fixture
def propagation_section(db):
    """TodoistSection record for the propagation section."""
    from todosync.models import TodoistSection

    return TodoistSection.objects.create(
        key="propagation",
        section_id="6f5xwW4prvPPrcR5",
        name="Propagation",
        project_id="6Jf8VQXxpwv56VQ7",
    )


@pytest.fixture
def sow_label_rule(db, propagation_section):
    """TaskRule: completing a task labelled 'sow' moves parent to 'propagation'."""
    from todosync.models import TaskRule

    return TaskRule.objects.create(
        rule_key="crop_label_completion_section",
        trigger="completed_task",
        condition="label:sow",
        action="section:propagation",
    )


def test_completed_task_with_sow_label_moves_to_propagation(
    client, crop_task_with_child, sow_label_rule, propagation_section
):
    """Completing a task with label 'sow' moves the parent to the propagation section."""
    body = _load_fixture("item_completed.json")
    mock_api = MagicMock()

    with patch("todosync.todoist_api.get_api_client", return_value=mock_api):
        response = client.post(WEBHOOK_URL, data=body, content_type="application/json")

    assert response.status_code == 200
    mock_api.move_task.assert_called_once_with(
        task_id="PARENT123",
        section_id=propagation_section.section_id,
    )


def test_completed_task_with_label_no_rules_no_move(client, crop_task_with_child):
    """No TaskRule records → no move attempted."""
    body = _load_fixture("item_completed.json")
    mock_api = MagicMock()

    with patch("todosync.todoist_api.get_api_client", return_value=mock_api):
        response = client.post(WEBHOOK_URL, data=body, content_type="application/json")

    assert response.status_code == 200
    mock_api.move_task.assert_not_called()
