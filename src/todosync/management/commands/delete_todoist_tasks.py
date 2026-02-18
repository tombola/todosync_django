import djclick as click
from django.conf import settings
from todoist_api_python.api import TodoistAPI
from rich.console import Console

from todosync.models import Task


@click.command()
@click.option("--dry-run", is_flag=True, help="Show what would be deleted without making changes.")
def command(dry_run):
    """Delete all Todoist tasks referenced by Django Task records and clear their todo_id."""
    console = Console()

    api_token = getattr(settings, "TODOIST_API_TOKEN", None)
    if not api_token:
        console.print("[red]Error:[/red] TODOIST_API_TOKEN not configured in settings.", style="bold")
        raise click.Abort()

    tasks = Task.objects.exclude(todo_id="")
    count = tasks.count()

    if count == 0:
        console.print("[yellow]No tasks with a todo_id found.[/yellow]")
        return

    console.print(f"Found [bold]{count}[/bold] task(s) with a todo_id.")

    if dry_run:
        for task in tasks:
            console.print(f"  Would delete Todoist task [dim]{task.todo_id}[/dim] — {task.title}")
        console.print(f"\n[yellow]Dry run — no changes made.[/yellow]")
        return

    if not click.confirm(f"Delete {count} task(s) from Todoist and clear their todo_id?"):
        raise click.Abort()

    api = TodoistAPI(api_token)
    deleted = 0
    failed = 0

    for task in tasks:
        try:
            api.delete_task(task_id=task.todo_id)
            console.print(f"  [green]Deleted[/green] {task.todo_id} — {task.title}")
            deleted += 1
        except Exception as e:
            console.print(f"  [red]Failed[/red] {task.todo_id} — {task.title}: {e}")
            failed += 1

    tasks.update(todo_id="")
    console.print(f"\n[green]Done.[/green] Deleted {deleted}, failed {failed}. Cleared todo_id on all {count} tasks.")
