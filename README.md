# TodoSync Django

Reusable Django/Wagtail package for Todoist task management integration.

## Features

- **Template-based task creation** with token substitution
- **Multi-table inheritance** for extensible task group templates
- **Direct Todoist API integration** (no abstraction layer)
- **Wagtail CMS** used for managing templates
- **Label-based rules** activated by webhook
- **Task groups** tracked as task instances

## Installation

### Using uv (recommended)

```bash
# As editable dependency for development
uv add --editable path/to/todosync-django

# From PyPI (once published)
uv add todosync-django
```

### Using pip

```bash
pip install -e path/to/todosync-django
```

## Quick Start

### 1. Add to Django settings

```python
# settings.py

INSTALLED_APPS = [
    # ...
    'wagtail.contrib.settings',
    'wagtail',
    'modelcluster',

    # Add todosync before your app
    'todosync',
    'your_app',
]

# Todoist API configuration
TODOIST_API_TOKEN = os.getenv('TODOIST_API_TOKEN', '')

# Optional: Enable debug mode to print tasks instead of creating them
DEBUG_TASK_CREATION = os.getenv('DEBUG_TASK_CREATION', 'False').lower() in ('true', '1', 'yes')
```

### 2. Include URLs

```python
# urls.py

from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('tasks/', include('todosync.urls')),  # Add todosync URLs
    path('', include(wagtail_urls)),
]
```

### 3. Run migrations

```bash
python manage.py migrate
```

### 4. Configure in Wagtail Admin

1. Go to **Settings → Task Sync Settings**
2. Configure:
   - **Tokens**: Comma-separated list (e.g., `SKU, VARIETYNAME`)
   - **Parent task title**: Template for parent task (optional)
   - **Description**: Site-wide description (optional)
   - **Todoist project ID**: Project where tasks are created (optional, uses inbox if empty)
   - **Label Action Rules**: Rules for moving completed tasks between sections

### 5. Create templates

1. In Wagtail admin, create a new **Task Group Template** page
2. Add tasks with titles using tokens (e.g., `Sow {SKU}`)
3. Add labels (e.g., `sow, plant`)
4. Add subtasks if needed

### 6. Create tasks

Visit `/tasks/create/` and:
1. Select a template
2. Enter token values
3. Click "Create Tasks"

## Extension Example

Extend the base template model for domain-specific fields:

```python
# your_app/models.py

from todosync.models import BaseTaskGroupTemplate
from django.db import models
from wagtail.admin.panels import FieldPanel


class CropTaskTemplate(BaseTaskGroupTemplate):
    """Crop-specific task template with bed location"""

    bed = models.CharField(
        max_length=100,
        blank=True,
        help_text="Bed location for this crop"
    )

    content_panels = BaseTaskGroupTemplate.content_panels + [
        FieldPanel('bed'),
    ]

    class Meta:
        verbose_name = 'Crop Task Template'


class BiennialCropTaskTemplate(CropTaskTemplate):
    """Biennial crop template - adds second-year bed location"""

    bed_second_year = models.CharField(
        max_length=100,
        blank=True,
        help_text="Bed location for second year growth"
    )

    content_panels = CropTaskTemplate.content_panels + [
        FieldPanel('bed_second_year'),
    ]

    class Meta:
        verbose_name = 'Biennial Crop Task Template'
```

This demonstrates:
- **Single extension**: CropTaskTemplate adds one field
- **Multi-level extension**: BiennialCropTaskTemplate extends CropTaskTemplate
- **Multi-table inheritance**: Each has its own database table with explicit joins

## Management Commands

### List Todoist Projects

```bash
python manage.py list_todoist_projects
```

Shows all your Todoist projects with their IDs. Use these IDs in the Task Sync Settings.

### List Todoist Sections

```bash
python manage.py list_todoist_sections [--project-id PROJECT_ID]
```

Shows all Todoist sections with their IDs. Optionally filter by project ID.

## Models

### TaskSyncSettings

Site-wide configuration for task creation:
- `tokens`: Comma-separated token names
- `parent_task_title`: Template for parent task title
- `description`: Site-wide description
- `todoist_project_id`: Todoist project ID

### LabelActionRule

Rules for moving completed tasks between sections based on labels (webhook support).

### BaseTaskGroupTemplate

Wagtail Page model for task templates:
- `description`: Template description
- `tasks`: StreamField with TaskBlock items

Extend this model for domain-specific templates.

### TaskGroup

Tracks created task groups:
- `template`: Link to the template used
- `token_values`: Token values used
- `parent_task_id`: Todoist parent task ID
- `created_at`: Creation timestamp

## Architecture

### Division of Responsibilities

**Package (generic features):**
- Token substitution system
- Template management with Wagtail
- Direct Todoist API integration
- Task group tracking
- Label-based routing rules
- Base models for extension

**Application (domain-specific):**
- Extended template models (e.g., CropTaskTemplate)
- Domain-specific fields and business rules
- Custom views and templates if needed
- Application configuration

### Multi-Table Inheritance

The package uses Django's multi-table inheritance for extensibility:

```
BaseTaskGroupTemplate (concrete Page model)
├── CropTaskTemplate (adds: bed)
│   └── BiennialCropTaskTemplate (adds: bed_second_year)
└── ProjectTaskTemplate (adds: client, deadline)
```

Each model creates its own table with a OneToOneField to the parent. This provides:
- Type safety (no generic foreign keys)
- Explicit joins
- Clean extension points
- Full Wagtail Page functionality

## License

MIT License (or your license here)

## Contributing

Contributions welcome! Please open an issue or pull request on GitHub.
