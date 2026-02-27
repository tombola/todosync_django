import djclick as click
import requests.exceptions
import stamina
from django.conf import settings
from rich.console import Console
from todoist_api_python.api import TodoistAPI

TEST_TASK_PREFIX = "Test task"


def _is_retryable_request_error(exc: Exception) -> bool:
    if isinstance(exc, requests.exceptions.HTTPError):
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    return isinstance(
        exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)
    )


@click.command()
@click.option(
    "--dry-run", is_flag=True, help="Show what would be deleted without making changes."
)
def command(dry_run):
    """Delete all Todoist tasks whose title starts with 'Test task'.

    Queries Todoist directly — not limited to tasks tracked in Django.
    """
    console = Console()

    api_token = getattr(settings, "TODOIST_API_TOKEN", None)
    if not api_token:
        console.print(
            "[red]Error:[/red] TODOIST_API_TOKEN not configured in settings.",
            style="bold",
        )
        raise click.Abort()

    api = TodoistAPI(api_token)

    console.print("[green]Fetching tasks from Todoist...[/green]")
    tasks = []
    for attempt in stamina.retry_context(on=_is_retryable_request_error):
        with attempt:
            for page in api.get_tasks():
                tasks.extend(page)

    matching = [t for t in tasks if t.content.startswith(TEST_TASK_PREFIX)]

    if not matching:
        console.print(
            f"[yellow]No tasks found starting with '{TEST_TASK_PREFIX}'.[/yellow]"
        )
        return

    console.print(
        f"Found [bold]{len(matching)}[/bold] task(s) starting with '{TEST_TASK_PREFIX}'."
    )

    if dry_run:
        for task in matching:
            console.print(f"  Would delete [dim]{task.id}[/dim] — {task.content}")
        console.print("\n[yellow]Dry run — no changes made.[/yellow]")
        return

    if not click.confirm(f"Delete {len(matching)} task(s) from Todoist?"):
        raise click.Abort()

    deleted = 0
    failed = 0
    for task in matching:
        try:
            for attempt in stamina.retry_context(on=_is_retryable_request_error):
                with attempt:
                    api.delete_task(task_id=task.id)
            console.print(f"  [green]Deleted[/green] {task.id} — {task.content}")
            deleted += 1
        except Exception as e:
            console.print(f"  [red]Failed[/red] {task.id} — {task.content}: {e}")
            failed += 1

    console.print(f"\n[green]Done.[/green] Deleted {deleted}, failed {failed}.")
