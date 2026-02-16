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
    from tasks.models import CropTaskGroupTemplate, CropTask

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


def test_completed_task_with_sow_label_moves_to_propagation(client, crop_task_with_child):
    """Completing a task with label 'sow' moves it to the propagation section."""
    from tasks.models import SECTIONS

    body = _load_fixture("item_completed.json")
    mock_api = MagicMock()

    with patch("todosync.todoist_api.get_api_client", return_value=mock_api):
        response = client.post(WEBHOOK_URL, data=body, content_type="application/json")

    assert response.status_code == 200
    mock_api.move_task.assert_called_once_with(
        task_id="PARENT123",
        section_id=SECTIONS["propagation"],
    )
