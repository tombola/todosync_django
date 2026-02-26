import djclick as click
import requests.exceptions
import stamina
from django.conf import settings
from rich.console import Console
from todoist_api_python.api import TodoistAPI

from todosync.models import Task


def _is_retryable_request_error(exc: Exception) -> bool:
    if isinstance(exc, requests.exceptions.HTTPError):
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    return isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout))


@click.command()
@click.option("--dry-run", is_flag=True, help="Show what would be deleted without making changes.")
@click.option("--task-id", type=int, multiple=True, help="Django Task pk(s) to target.")
@click.option("--todo-id", type=str, multiple=True, help="Todoist task ID(s) to target.")
@click.option("--hidden", is_flag=True, help="Only target tasks where hide > 0.")
def command(dry_run, task_id, todo_id, hidden):
    """Delete Todoist tasks referenced by Django Task records and clear their todo_id.

    With no filters, targets all tasks with a todo_id. Use --task-id or --todo-id
    (repeatable) to target specific tasks.
    """
    console = Console()

    api_token = getattr(settings, "TODOIST_API_TOKEN", None)
    if not api_token:
        console.print("[red]Error:[/red] TODOIST_API_TOKEN not configured in settings.", style="bold")
        raise click.Abort()

    tasks = Task.objects.exclude(todo_id="").exclude(templatetask__isnull=False)
    if hidden:
        tasks = tasks.filter(hide__gt=0)
    if task_id:
        tasks = tasks.filter(pk__in=task_id)
    if todo_id:
        tasks = tasks.filter(todo_id__in=todo_id)
    count = tasks.count()

    if count == 0:
        console.print("[yellow]No tasks with a todo_id found.[/yellow]")
        return

    console.print(f"Found [bold]{count}[/bold] task(s) with a todo_id.")

    if dry_run:
        for task in tasks:
            console.print(f"  Would delete Todoist task [dim]{task.todo_id}[/dim] — {task.title}")
        console.print("\n[yellow]Dry run — no changes made.[/yellow]")
        return

    if not click.confirm(f"Delete {count} task(s) from Todoist and clear their todo_id?"):
        raise click.Abort()

    api = TodoistAPI(api_token)
    deleted = 0
    failed = 0

    for task in tasks:
        try:
            for attempt in stamina.retry_context(on=_is_retryable_request_error):
                with attempt:
                    api.delete_task(task_id=task.todo_id)
            console.print(f"  [green]Deleted[/green] {task.todo_id} — {task.title}")
            deleted += 1
        except Exception as e:
            console.print(f"  [red]Failed[/red] {task.todo_id} — {task.title}: {e}")
            failed += 1

    tasks.update(todo_id="")
    console.print(f"\n[green]Done.[/green] Deleted {deleted}, failed {failed}. Cleared todo_id on all {count} tasks.")
