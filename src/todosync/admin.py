from django.contrib import admin
from .models import TaskGroup


@admin.register(TaskGroup)
class TaskGroupAdmin(admin.ModelAdmin):
    list_display = ['template', 'parent_task_id', 'created_at']
    list_filter = ['created_at']
    search_fields = ['parent_task_id']
    readonly_fields = ['template', 'token_values', 'parent_task_id', 'created_at']

    def has_add_permission(self, request):
        # TaskGroups are created programmatically, not manually
        return False
