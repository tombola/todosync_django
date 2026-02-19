import djclick as click
from rich.console import Console

from todosync.models import BaseParentTask, Task


@click.command()
@click.option("--dry-run", is_flag=True, help="Show what would be deleted without making changes.")
@click.option("--template-id", type=int, default=None, help="Only delete tasks from this template (by pk).")
@click.option("--template-name", type=str, default=None, help="Only delete tasks from this template (by title, case-insensitive).")
def command(dry_run, template_id, template_name):
    """Delete all Django Task and BaseParentTask records. Templates are not affected.

    Deleting a BaseParentTask cascades to its child Task records.
    Use --template-id or --template-name to scope deletion to a single template.
    """
    console = Console()

    parent_tasks = BaseParentTask.objects.select_related("template")

    if template_id:
        parent_tasks = parent_tasks.filter(template_id=template_id)
    elif template_name:
        parent_tasks = parent_tasks.filter(template__title__iexact=template_name)

    filtered = template_id is not None or template_name is not None

    parent_count = parent_tasks.count()
    child_count = Task.objects.filter(parent_task__in=parent_tasks).count()
    # Orphan tasks: tasks with no parent_task and not themselves a BaseParentTask
    orphan_tasks = Task.objects.filter(parent_task__isnull=True, baseparenttask__isnull=True)
    orphan_count = 0 if filtered else orphan_tasks.count()

    total = parent_count + child_count + orphan_count

    if total == 0:
        console.print("[yellow]No tasks found.[/yellow]")
        return

    if filtered:
        template = parent_tasks.first().template if parent_count else None
        template_title = template.title if template else "(unknown)"
        console.print(f"\nTemplate: [bold]{template_title}[/bold]\n")

        for pt in parent_tasks:
            pt_child_count = Task.objects.filter(parent_task=pt).count()
            console.print(f"  [bold]{pt.title}[/bold] (pk={pt.pk}) — {pt_child_count} child task(s)")

        console.print(f"\nTotal: [bold]{parent_count}[/bold] parent task(s), [bold]{child_count}[/bold] child task(s)")
    else:
        console.print(f"Found [bold]{parent_count}[/bold] parent task(s), [bold]{child_count}[/bold] child task(s)", end="")
        if orphan_count:
            console.print(f", [bold]{orphan_count}[/bold] orphan task(s)")
        else:
            console.print()

    if dry_run:
        console.print("\n[yellow]Dry run — no changes made.[/yellow]")
        return

    if not click.confirm(f"\nDelete {total} task record(s) from the database?"):
        raise click.Abort()

    deleted_total = 0
    # Delete parent tasks (cascades to child tasks via FK)
    if parent_count:
        count, _ = parent_tasks.delete()
        deleted_total += count
    # Delete orphan tasks (no parent_task, not a BaseParentTask)
    if orphan_count:
        count, _ = orphan_tasks.delete()
        deleted_total += count

    console.print(f"\n[green]Done.[/green] Deleted {deleted_total} record(s). Templates untouched.")
