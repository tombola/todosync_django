from django.contrib import admin
from .models import BaseParentTask, Task


class TaskInline(admin.TabularInline):
    model = Task
    fk_name = 'parent_task'
    extra = 0
    readonly_fields = ['todoist_id', 'title', 'created_at']

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(BaseParentTask)
class BaseParentTaskAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'template', 'todoist_id', 'created_at']
    list_filter = ['created_at']
    readonly_fields = ['template', 'todoist_id', 'created_at']
    inlines = [TaskInline]

    def has_add_permission(self, request):
        return False


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['title', 'parent_task', 'todoist_id', 'created_at']
    readonly_fields = ['parent_task', 'todoist_id', 'title', 'created_at']
    inlines = [TaskInline]

    def has_add_permission(self, request):
        return False
