from django.contrib import admin
from django.db import models as db_models
from django.forms import TextInput

from .models import (
    BaseParentTask,
    BaseTaskGroupTemplate,
    LabelActionRule,
    Task,
    TaskRule,
    TaskSyncSettings,
    TemplateTask,
    TodoistSection,
)


class TemplateTaskInline(admin.TabularInline):
    model = TemplateTask
    extra = 1
    fields = ["order", "title", "description", "due_date", "depends_on"]
    ordering = ["order", "pk"]
    formfield_overrides = {
        db_models.PositiveIntegerField: {
            "widget": TextInput(attrs={"style": "width: 3em;"})
        },
        db_models.TextField: {"widget": TextInput()},
    }


@admin.register(BaseTaskGroupTemplate)
class BaseTaskGroupTemplateAdmin(admin.ModelAdmin):
    list_display = ["title", "project_id", "created_at"]
    inlines = [TemplateTaskInline]


class LabelActionRuleInline(admin.TabularInline):
    model = LabelActionRule
    extra = 1


@admin.register(TaskSyncSettings)
class TaskSyncSettingsAdmin(admin.ModelAdmin):
    inlines = [LabelActionRuleInline]

    def has_add_permission(self, request):
        return not TaskSyncSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class TaskInline(admin.TabularInline):
    model = Task
    fk_name = "parent_task"
    extra = 0
    readonly_fields = ["todo_id", "title", "template_task", "created_at"]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(BaseParentTask)
class BaseParentTaskAdmin(admin.ModelAdmin):
    list_display = ["__str__", "template", "todo_id", "created_at"]
    list_filter = ["created_at"]
    readonly_fields = ["template", "todo_id", "created_at"]
    inlines = [TaskInline]

    def has_add_permission(self, request):
        return False


@admin.register(TodoistSection)
class TodoistSectionAdmin(admin.ModelAdmin):
    list_display = ["key", "name", "section_id", "project_id"]
    search_fields = ["key", "name", "section_id"]
    readonly_fields = ["section_id", "name", "project_id"]


@admin.register(TaskRule)
class TaskRuleAdmin(admin.ModelAdmin):
    list_display = ["rule_key", "trigger", "task_type", "condition", "action"]
    list_filter = ["rule_key", "trigger"]
    search_fields = ["condition", "action"]


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "parent_task",
        "template_task",
        "depends_on",
        "todo_id",
        "created_at",
    ]
    readonly_fields = [
        "parent_task",
        "template_task",
        "depends_on",
        "todo_id",
        "title",
        "created_at",
    ]

    def has_add_permission(self, request):
        return False
