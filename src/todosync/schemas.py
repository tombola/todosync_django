"""Pydantic schemas for Todoist webhook payloads."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class WebhookEventType(StrEnum):
    ITEM_ADDED = "item:added"
    ITEM_UPDATED = "item:updated"
    ITEM_DELETED = "item:deleted"
    ITEM_COMPLETED = "item:completed"
    ITEM_UNCOMPLETED = "item:uncompleted"


class Duration(BaseModel):
    amount: int
    unit: Literal["minute", "day"]


class TodoistItem(BaseModel):
    """Todoist task/item object from webhook event_data."""

    id: str
    user_id: str | None = None
    project_id: str | None = None
    content: str
    description: str = ""
    priority: int = 1
    parent_id: str | None = None
    child_order: int | None = None
    section_id: str | None = None
    day_order: int | None = None
    is_collapsed: bool = False
    labels: list[str] = []
    added_by_uid: str | None = None
    assigned_by_uid: str | None = None
    responsible_uid: str | None = None
    checked: bool = False
    is_deleted: bool = False
    added_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None
    duration: Duration | None = None


class TodoistWebhookPayload(BaseModel):
    """Top-level webhook request body from Todoist."""

    event_name: WebhookEventType
    event_data: TodoistItem
