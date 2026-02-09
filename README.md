# TodoSync Django

Reusable Django/Wagtail package for Todoist task management integration.

## Features

- Template-based task creation with token substitution
- Multi-table inheritance for extensible task group templates
- Direct Todoist API integration
- Wagtail CMS integration
- Label-based routing rules for webhooks

## Installation

```bash
# As editable dependency for development
uv add --editable path/to/todosync-django
```

## Quick Start

Add to your Django settings:

```python
INSTALLED_APPS = [
    'todosync',
    'your_app',
]
```

See full documentation (coming soon) for usage examples.
