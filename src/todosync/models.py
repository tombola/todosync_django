from django.contrib.contenttypes.models import ContentType
from django.db import models
from wagtail.models import Page
from wagtail.fields import StreamField
from wagtail.admin.panels import FieldPanel, InlinePanel
from wagtail.contrib.settings.models import BaseSiteSetting, register_setting
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel

from .blocks import TaskBlock


class LabelActionRule(models.Model):
    """Rule for moving completed tasks to different sections based on label"""

    settings = ParentalKey(
        'TaskSyncSettings',
        on_delete=models.CASCADE,
        related_name='label_action_rules'
    )

    source_section_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="Todoist section ID to monitor for completed tasks with this label"
    )

    label = models.CharField(
        max_length=100,
        help_text="Label to match (e.g., 'harvest', 'plant')"
    )

    destination_section_id = models.CharField(
        max_length=100,
        help_text="Todoist section ID where completed tasks with this label should be moved"
    )

    panels = [
        FieldPanel('source_section_id'),
        FieldPanel('label'),
        FieldPanel('destination_section_id'),
    ]

    class Meta:
        verbose_name = 'Label Action Rule'
        verbose_name_plural = 'Label Action Rules'

    def __str__(self):
        return f"Section {self.source_section_id}: {self.label} → Section {self.destination_section_id}"


@register_setting
class TaskSyncSettings(ClusterableModel, BaseSiteSetting):
    """Site-wide settings for task sync"""

    todoist_project_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="Default Todoist project ID. Templates can override this per-template."
    )

    panels = [
        FieldPanel('todoist_project_id'),
        InlinePanel('label_action_rules', label="Label Action Rules", heading="Rules for moving completed tasks between sections"),
    ]

    class Meta:
        verbose_name = 'Task Sync Settings'


class BaseTaskGroupTemplate(Page):
    """Wagtail page type for task group templates"""

    task_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        help_text="The type of parent task to create from this template"
    )

    todoist_project_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="Todoist project ID. If empty, uses the default from Task Sync Settings."
    )

    description = models.TextField(
        blank=True,
        help_text="Description for this template (can use tokens). Appended to parent task description."
    )

    tasks = StreamField([
        ('task', TaskBlock()),
    ], blank=True, use_json_field=True)

    content_panels = Page.content_panels + [
        FieldPanel('task_type'),
        FieldPanel('todoist_project_id'),
        FieldPanel('description'),
        FieldPanel('tasks'),
    ]

    template = 'todosync/base_task_group_template.html'

    class Meta:
        verbose_name = 'Task Group Template'
        verbose_name_plural = 'Task Group Templates'

    def get_effective_project_id(self, site):
        """Return todoist_project_id, falling back to TaskSyncSettings default."""
        if self.todoist_project_id:
            return self.todoist_project_id
        sync_settings = TaskSyncSettings.for_site(site)
        return sync_settings.todoist_project_id

    def get_parent_task_model(self):
        """Return the model class for creating parent tasks."""
        if self.task_type:
            return self.task_type.model_class()
        return None

    def get_token_field_names(self):
        """Return token field names from the associated parent task model."""
        model = self.get_parent_task_model()
        if model:
            return model.get_token_field_names()
        return []

    def get_context(self, request, *args, **kwargs):
        context = super().get_context(request, *args, **kwargs)
        context['token_field_names'] = self.get_token_field_names()
        return context


class BaseParentTask(models.Model):
    """Base model for parent tasks created from templates.

    Subclass this to add domain-specific fields (e.g., sku, variety_name).
    Field names returned by get_token_field_names() serve as token names;
    field values serve as token values for substitution in task titles.
    """

    todoist_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="Todoist task ID for the parent task"
    )

    template = models.ForeignKey(
        BaseTaskGroupTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='parent_tasks',
        help_text="Template used to create this parent task"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Parent Task'
        verbose_name_plural = 'Parent Tasks'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.__class__.__name__} ({self.created_at.strftime('%Y-%m-%d')})"

    @classmethod
    def get_token_field_names(cls):
        """Return list of field names to use as tokens. Override in subclasses."""
        return []

    def get_token_values(self):
        """Return dict mapping token field names to their values."""
        return {
            field_name: getattr(self, field_name, '')
            for field_name in self.get_token_field_names()
        }

    def get_parent_task_title(self):
        """Return the title for the Todoist parent task. Override in subclasses."""
        if self.template:
            return self.template.title
        return ''

    def get_description(self):
        """Return the description for the Todoist parent task. Override in subclasses."""
        return ''


class Task(models.Model):
    """Represents a task created under a parent task in Todoist."""

    parent_task = models.ForeignKey(
        BaseParentTask,
        on_delete=models.CASCADE,
        related_name='tasks'
    )

    todoist_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="Todoist task ID"
    )

    title = models.CharField(
        max_length=500,
        help_text="Task title as sent to Todoist"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Task'
        verbose_name_plural = 'Tasks'
        ordering = ['created_at']

    def __str__(self):
        return self.title


class SubTask(models.Model):
    """Represents a subtask created under a task in Todoist."""

    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='subtasks'
    )

    todoist_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="Todoist subtask ID"
    )

    title = models.CharField(
        max_length=500,
        help_text="Subtask title as sent to Todoist"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Sub Task'
        verbose_name_plural = 'Sub Tasks'
        ordering = ['created_at']

    def __str__(self):
        return self.title
