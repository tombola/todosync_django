"""Sync completed Todoist tasks back to Django.

Fetches tasks completed in Todoist within the given window and marks any
corresponding Django Task records as completed if they are not already.
"""

import logging
from datetime import datetime, timedelta, timezone

import djclick as click
import requests.exceptions
import stamina
from django.conf import settings
from rich.console import Console
from rich.table import Table
from todoist_api_python.api import TodoistAPI

from todosync.models import Task, TodoistUser

action_log = logging.getLogger("actions")
logger = logging.getLogger("todosync")


def _is_retryable_request_error(exc: Exception) -> bool:
    if isinstance(exc, requests.exceptions.HTTPError):
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    return isinstance(
        exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)
    )


def _get_api_token() -> str:
    api_token = getattr(settings, "TODOIST_API_TOKEN", None)
    if not api_token:
        Console().print("[red]Error:[/red] TODOIST_API_TOKEN not configured.")
        raise click.Abort()
    return api_token


def _resolve_completed_by(assignee_id: str | None) -> TodoistUser | None:
    if not assignee_id:
        return None
    return TodoistUser.objects.filter(todoist_id=assignee_id).first()


def _mark_django_task_complete(task: Task, todoist_task, dry_run: bool) -> bool:
    """Mark task as complete. Returns True if an update was made."""
    if task.completed:
        return False

    completed_at = None
    if getattr(todoist_task, "completed_at", None):
        raw = todoist_task.completed_at
        if isinstance(raw, str):
            try:
                completed_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                logger.warning("Could not parse completed_at: %s", raw)
        elif isinstance(raw, datetime):
            completed_at = raw

    completed_by = _resolve_completed_by(getattr(todoist_task, "assignee_id", None))

    if not dry_run:
        task.completed = True
        task.completed_at = completed_at
        task.completed_by = completed_by
        task.save(update_fields=["completed", "completed_at", "completed_by"])
        action_log.info("todoist: completed_task %s", task.pk)

    return True


@click.command()
@click.option(
    "--days",
    default=90,
    show_default=True,
    help="Look back this many days for completed tasks (max 90)",
)
@click.option("--dry-run", is_flag=True, help="Show what would change without writing")
def command(days, dry_run):
    """Sync completed Todoist tasks to Django.

    Fetches tasks completed in Todoist within the last DAYS days, cross-references
    with Django Task records by todo_id, and marks any unresolved tasks as complete.
    Sets completed_at from Todoist and completed_by from the task assignee (if a
    matching TodoistUser record already exists).
    """
    console = Console()
    api_token = _get_api_token()

    if days > 90:
        console.print("[yellow]Warning:[/yellow] --days capped at 90 (API limit).")
        days = 90

    try:
        api = TodoistAPI(api_token)

        # Restrict the completed-tasks window per --days option by temporarily
        # fetching via the function with completed=None (all Django IDs), then
        # applying the window manually using a direct API call subset.
        # Simpler: pass completed=None and let the function use 90 days,
        # but honour --days by fetching only that window ourselves.
        django_open_ids = set(
            Task.objects.filter(completed=False)
            .exclude(todo_id="")
            .values_list("todo_id", flat=True)
        )

        if not django_open_ids:
            console.print("[yellow]No open Django tasks with a todo_id found.[/yellow]")
            return

        until = datetime.now(tz=timezone.utc)
        since = until - timedelta(days=days)

        console.print(
            f"[green]Fetching Todoist completed tasks "
            f"({since.date()} → {until.date()})...[/green]"
        )

        completed_todoist_tasks = []
        for attempt in stamina.retry_context(on=_is_retryable_request_error):
            with attempt:
                for page in api.get_completed_tasks_by_completion_date(
                    since=since, until=until
                ):
                    items = page if isinstance(page, list) else [page]
                    completed_todoist_tasks.extend(
                        t for t in items if t.id in django_open_ids
                    )

        if not completed_todoist_tasks:
            console.print("[yellow]No matching completed tasks found.[/yellow]")
            return

        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Django PK", width=10)
        table.add_column("Title", width=40)
        table.add_column("Completed At", width=22)
        table.add_column("Completed By", width=20)
        table.add_column("Status", width=12)

        updated = 0
        for todoist_task in completed_todoist_tasks:
            try:
                task = Task.objects.get(todo_id=todoist_task.id)
            except Task.DoesNotExist:
                continue

            completed_by = _resolve_completed_by(
                getattr(todoist_task, "assignee_id", None)
            )
            was_updated = _mark_django_task_complete(task, todoist_task, dry_run)

            if was_updated:
                updated += 1
                status = (
                    "[yellow]dry-run[/yellow]" if dry_run else "[green]updated[/green]"
                )
            else:
                status = "[dim]already done[/dim]"

            completed_at_str = str(getattr(todoist_task, "completed_at", "") or "")
            completed_by_str = str(completed_by) if completed_by else "-"
            table.add_row(
                str(task.pk),
                task.title[:40],
                completed_at_str[:22],
                completed_by_str[:20],
                status,
            )

        console.print(table)

        if dry_run:
            console.print(
                f"[yellow]Dry run:[/yellow] {updated} task(s) would be marked complete."
            )
        else:
            console.print(f"[green]Done:[/green] {updated} task(s) marked complete.")

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise click.Abort()
