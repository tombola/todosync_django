from wagtail import blocks


class TaskBlock(blocks.StructBlock):
    """Block for a single task with title and labels"""
    title = blocks.CharBlock(required=True, help_text="Task title (can use tokens like {SKU})")
    labels = blocks.CharBlock(required=False, help_text="Comma-separated labels (e.g., sow, plant)")
    subtasks = blocks.ListBlock(
        blocks.StructBlock([
            ('title', blocks.CharBlock(required=True, help_text="Subtask title (can use tokens)")),
            ('labels', blocks.CharBlock(required=False, help_text="Comma-separated labels")),
        ]),
        required=False,
        help_text="Subtasks for this task"
    )

    class Meta:
        icon = 'task'
        label = 'Task'
