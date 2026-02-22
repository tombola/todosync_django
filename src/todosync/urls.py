from django.urls import path

from . import views
from .todoist_api import todoist_webhook

app_name = "todosync"

urlpatterns = [
    path("create/", views.create_task_group, name="create_task_group"),
    path("webhook/todoist/", todoist_webhook, name="todoist_webhook"),
]
