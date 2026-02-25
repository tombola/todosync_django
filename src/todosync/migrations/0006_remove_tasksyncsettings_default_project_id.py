from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("todosync", "0005_task_hide"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="tasksyncsettings",
            name="default_project_id",
        ),
    ]
