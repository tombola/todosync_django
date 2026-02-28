from django.conf import settings as django_settings
from django.core.exceptions import ValidationError
from django.db import models
from polymorphic.models import PolymorphicModel
from taggit.managers import TaggableManager


class LabelActionRule(models.Model):
    """Rule for moving completed tasks to different sections based on label"""

    settings = models.ForeignKey(
        "TaskSyncSettings", on_delete=models.CASCADE, related_name="label_action_rules"
    )

    source_section_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="Todoist section ID to monitor for completed tasks with this label",
    )

    label = models.CharField(
        max_length=100, help_text="Label to match (e.g., 'harvest', 'plant')"
    )

    destination_section_id = models.CharField(
        max_length=100,
        help_text="Todoist section ID where completed tasks with this label should be moved",
    )

    class Meta:
        verbose_name = "Label Action Rule"
        verbose_name_plural = "Label Action Rules"

    def __str__(self):
        return f"Section {self.source_section_id}: {self.label} → Section {self.destination_section_id}"


class TodoistSection(models.Model):
    """A Todoist section, synced from the Todoist API.

    The key slug is used in TaskRule actions to reference a section by
    human-readable name rather than raw section_id. The key is preserved
    across syncs so rules remain valid after a Todoist rename.
    """

    key = models.SlugField(
        max_length=100,
        unique=True,
        help_text="Human-readable slug (e.g. 'propagation'). Set by admin; preserved on sync.",
    )
    section_id = models.CharField(
        max_length=100,
        unique=True,
        help_text="Todoist section ID",
    )
    name = models.CharField(
        max_length=255,
        help_text="Section name synced from Todoist API",
    )
    project_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="Todoist project ID this section belongs to",
    )

    class Meta:
        verbose_name = "Todoist Section"
        verbose_name_plural = "Todoist Sections"
        ordering = ["project_id", "name"]

    def __str__(self):
        return f"{self.key} ({self.section_id})"


class TaskRule(models.Model):
    """A rule that triggers an action on a task event.

    Condition format: 'label:<label_name>'  (e.g. 'label:sow')
    Action format:    'section:<key>'       (e.g. 'section:propagation')

    The section key is resolved via TodoistSection.key at rule evaluation time.
    """

    task_type = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Task type label to scope rule to (e.g. 'crop'). Null matches all types.",
    )
    rule_key = models.CharField(
        max_length=100,
        help_text="Namespaced key grouping related rules (e.g. 'crop_label_completion_section')",
    )
    trigger = models.CharField(
        max_length=100,
        help_text="Event that activates this rule (e.g. 'completed_task')",
    )
    condition = models.CharField(
        max_length=255,
        help_text="Match condition in 'type:value' format (e.g. 'label:sow')",
    )
    action = models.CharField(
        max_length=255,
        help_text="Action to perform in 'type:value' format (e.g. 'section:propagation')",
    )

    def clean(self):
        errors = {}
        if self.condition and self.condition.startswith("label:"):
            from taggit.models import Tag

            slug = self.condition.split(":", 1)[1]
            if not Tag.objects.filter(slug=slug).exists():
                errors["condition"] = f"Label slug '{slug}' does not match any tag."
        if self.action and self.action.startswith("section:"):
            key = self.action.split(":", 1)[1]
            if not TodoistSection.objects.filter(key=key).exists():
                errors["action"] = f"Section key '{key}' does not match any TodoistSection."
        if errors:
            raise ValidationError(errors)

    class Meta:
        verbose_name = "Task Rule"
        verbose_name_plural = "Task Rules"
        ordering = ["rule_key", "trigger"]
        indexes = [
            models.Index(fields=["rule_key", "trigger"]),
        ]

    def __str__(self):
        prefix = f"[{self.task_type}] " if self.task_type else ""
        return f"{prefix}{self.rule_key}: {self.condition} → {self.action}"


class TaskSyncSettings(models.Model):
    """Site-wide settings for task sync. Only one instance should exist."""

    class Meta:
        verbose_name = "Task Sync Settings"
        verbose_name_plural = "Task Sync Settings"

    def __str__(self):
        return "Task Sync Settings"

    def save(self, *args, **kwargs):
        # Enforce singleton: always use pk=1
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class BaseTaskGroupTemplate(PolymorphicModel):
    """Task group template for defining reusable task structures.

    Subclasses should set parent_task_class to a BaseParentTask subclass.
    """

    parent_task_class = None

    title = models.CharField(max_length=255)

    created_at = models.DateTimeField(auto_now_add=True, null=True)

    project_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="Project ID for task sync. If empty, uses the default from Task Sync Settings.",
    )

    description = models.TextField(
        blank=True,
        help_text="Description for this template (can use tokens). Appended to parent task description.",
    )

    tags = TaggableManager(blank=True, help_text="Tags for this template")

    class Meta:
        verbose_name = "Task Group Template"
        verbose_name_plural = "Task Group Templates"

    def __str__(self):
        return self.title

    def get_effective_project_id(self):
        """Return project_id, falling back to TODOIST_PROJECT_ID setting."""
        if self.project_id:
            return self.project_id
        return getattr(django_settings, "TODOIST_PROJECT_ID", "")

    def get_parent_task_model(self):
        """Return the model class for creating parent tasks."""
        return self.parent_task_class

    def get_token_field_names(self):
        """Return token field names from the associated parent task model."""
        model = self.get_parent_task_model()
        if model:
            return model.get_token_field_names()
        return []


class Task(models.Model):
    """Represents a task synced with an external service (e.g. Todoist).

    All tasks belong to a BaseParentTask via the parent_task FK.
    Tasks are flat — no subtask nesting. Use depends_on to express ordering.
    """

    todo_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="Task ID from external task management service",
    )
    title = models.CharField(
        max_length=500, help_text="Task title as sent to external service"
    )
    todo_section_id = models.CharField(
        max_length=50,
        blank=True,
        null=False,
        help_text="Section ID from external service — used as column in kanban board",
    )
    completed = models.BooleanField(default=False)
    due_date = models.DateField(
        null=True, blank=True, help_text="Due date for this task"
    )
    parent_task = models.ForeignKey(
        "BaseParentTask",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="child_tasks",
        help_text="The parent task group this task belongs to",
    )
    template_task = models.ForeignKey(
        "TemplateTask",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_tasks",
        help_text="The template task this was created from",
    )
    depends_on = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dependents",
        help_text="Task that must be completed before this one",
    )

    description = models.TextField(
        blank=True,
        help_text="Description for this task",
    )

    tags = TaggableManager(blank=True, help_text="Tags for this task")

    created_at = models.DateTimeField(auto_now_add=True)

    hide = models.BooleanField(
        default=True,
        help_text="If True, this task will be hidden in the external service until relevant",
    )

    class Meta:
        verbose_name = "Task"
        verbose_name_plural = "Tasks"
        ordering = ["created_at"]

    def __str__(self):
        return self.title


class TemplateTask(Task):
    """A task definition within a template, extending Task via multi-table inheritance.

    TemplateTask instances are prototype tasks that get copied ("stamped") when a
    template is used. They inherit all Task fields (title, due_date, depends_on, tags, etc.)
    and add template-specific fields (template FK, order).
    """

    template = models.ForeignKey(
        BaseTaskGroupTemplate,
        on_delete=models.CASCADE,
        related_name="template_tasks",
        help_text="Template this task belongs to",
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Sort order within the parent or template",
    )

    class Meta:
        verbose_name = "Template Task"
        verbose_name_plural = "Template Tasks"
        ordering = ["order", "pk"]


class BaseParentTask(Task):
    """Base model for parent tasks created from templates.

    Subclass this to add domain-specific fields (e.g., sku, variety_name).
    Field names returned by get_token_field_names() serve as token names;
    field values serve as token values for substitution in task titles.
    """

    template = models.ForeignKey(
        BaseTaskGroupTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="parent_tasks",
        help_text="Template used to create this parent task",
    )

    class Meta:
        verbose_name = "Parent Task"
        verbose_name_plural = "Parent Tasks"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.__class__.__name__} ({self.created_at.strftime('%Y-%m-%d')})"

    @classmethod
    def get_token_field_names(cls):
        """Return list of field names to use as tokens. Override in subclasses."""
        return []

    def get_token_values(self):
        """Return dict mapping token field names to their values."""
        return {
            field_name: getattr(self, field_name, "")
            for field_name in self.get_token_field_names()
        }

    def get_parent_task_title(self):
        """Return the title for the Todoist parent task. Override in subclasses."""
        if self.template:
            return self.template.title
        return ""

    def get_description(self):
        """Return the description for the Todoist parent task. Override in subclasses."""
        return ""
