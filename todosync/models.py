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

    tokens = models.CharField(
        max_length=500,
        blank=True,
        help_text="Comma-separated list of tokens (e.g., SKU, VARIETYNAME)"
    )

    parent_task_title = models.CharField(
        max_length=200,
        blank=True,
        help_text="Title template for parent task (can use tokens like {SKU}). If empty, uses the template page title."
    )

    description = models.TextField(
        blank=True,
        help_text="Description template for parent task (can use tokens like {SKU}). This will be prepended to the template description."
    )

    todoist_project_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="Todoist project ID where tasks should be created. Leave empty to create tasks in the inbox."
    )

    panels = [
        FieldPanel('tokens'),
        FieldPanel('parent_task_title'),
        FieldPanel('description'),
        FieldPanel('todoist_project_id'),
        InlinePanel('label_action_rules', label="Label Action Rules", heading="Rules for moving completed tasks between sections"),
    ]

    class Meta:
        verbose_name = 'Task Sync Settings'

    def get_token_list(self):
        """Return list of tokens from comma-separated string"""
        if not self.tokens:
            return []
        return [token.strip() for token in self.tokens.split(',') if token.strip()]


class BaseTaskGroupTemplate(Page):
    """Wagtail page type for task group templates"""

    description = models.TextField(
        blank=True,
        help_text="Description for this template (can use tokens like {SKU}). This will be appended to the site-wide description."
    )

    tasks = StreamField([
        ('task', TaskBlock()),
    ], blank=True, use_json_field=True)

    content_panels = Page.content_panels + [
        FieldPanel('description'),
        FieldPanel('tasks'),
    ]

    template = 'todosync/base_task_group_template.html'

    class Meta:
        verbose_name = 'Task Group Template'
        verbose_name_plural = 'Task Group Templates'


class TaskGroup(models.Model):
    """Tracks each created set of tasks"""

    template = models.ForeignKey(
        BaseTaskGroupTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='task_groups',
        help_text="Template used to create this task group"
    )

    token_values = models.JSONField(
        default=dict,
        help_text="Token values used when creating this task group"
    )

    parent_task_id = models.CharField(
        max_length=100,
        help_text="Todoist parent task ID"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Task Group'
        verbose_name_plural = 'Task Groups'
        ordering = ['-created_at']

    def __str__(self):
        template_name = self.template.title if self.template else "Unknown"
        return f"Task Group from {template_name} ({self.created_at.strftime('%Y-%m-%d')})"
