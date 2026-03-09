from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("todosync", "0007_todoistsection_taskrule"),
    ]

    operations = [
        migrations.DeleteModel(
            name="TaskRule",
        ),
        migrations.DeleteModel(
            name="LabelActionRule",
        ),
    ]
