from dataclasses import dataclass, field

import djclick as click
import requests.exceptions
import stamina
from django.conf import settings
from django.utils.text import slugify
from rich.console import Console
from rich.table import Table
from todoist_api_python.api import TodoistAPI

from todosync.models import TodoistSection


def _is_retryable_request_error(exc: Exception) -> bool:
    if isinstance(exc, requests.exceptions.HTTPError):
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    return isinstance(
        exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)
    )


def _unique_slug(name: str, existing_keys: set) -> str:
    """Return a slugified key that does not collide with existing_keys."""
    base = slugify(name)
    candidate = base
    counter = 1
    while candidate in existing_keys:
        candidate = f"{base}-{counter}"
        counter += 1
    existing_keys.add(candidate)
    return candidate


def _get_api_token() -> str:
    """Return the Todoist API token or abort if not configured."""
    api_token = getattr(settings, "TODOIST_API_TOKEN", None)
    if not api_token:
        Console().print(
            "[red]Error:[/red] TODOIST_API_TOKEN not configured.", style="bold"
        )
        raise click.Abort()
    return api_token


def _fetch_sections(api: TodoistAPI, project_id: str | None) -> list:
    """Fetch sections from Todoist with retry logic, returning a flat list."""
    for attempt in stamina.retry_context(on=_is_retryable_request_error):
        with attempt:
            paginator = (
                api.get_sections(project_id=project_id)
                if project_id
                else api.get_sections()
            )
            sections = []
            for page in paginator:
                if isinstance(page, list):
                    sections.extend(page)
                else:
                    sections.append(page)
    return sections


@dataclass
class SyncCounts:
    created: int = 0
    updated: int = 0
    unchanged: int = 0


@dataclass
class SectionSyncResult:
    status: str
    key: str
    counts: SyncCounts = field(default_factory=SyncCounts)


def _sync_existing_section(obj, section, dry_run: bool) -> SectionSyncResult:
    """Sync an existing TodoistSection record, returning status and key."""
    changed = obj.name != section.name or obj.project_id != section.project_id
    result = SectionSyncResult(status="", key=obj.key)
    if changed:
        if not dry_run:
            obj.name = section.name
            obj.project_id = section.project_id
            obj.save(update_fields=["name", "project_id"])
        result.status = "[yellow]updated[/yellow]"
        result.counts.updated = 1
    else:
        result.status = "[dim]no change[/dim]"
        result.counts.unchanged = 1
    return result


def _create_section(section, existing_keys: set, dry_run: bool) -> SectionSyncResult:
    """Create a new TodoistSection record, returning status and key."""
    key = _unique_slug(section.name, existing_keys)
    if not dry_run:
        TodoistSection.objects.create(
            key=key,
            section_id=section.id,
            name=section.name,
            project_id=section.project_id,
        )
    return SectionSyncResult(
        status="[green]created[/green]",
        key=key,
        counts=SyncCounts(created=1),
    )


def _build_results_table() -> Table:
    """Build a Rich table for displaying sync results."""
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Status", width=12)
    table.add_column("Key", width=20)
    table.add_column("Name", width=30)
    table.add_column("Section ID", width=25)
    table.add_column("Project ID", width=25)
    return table


def _print_summary(console: Console, dry_run: bool, counts: SyncCounts) -> None:
    """Print the final summary line."""
    if dry_run:
        console.print(
            f"[yellow]Dry run:[/yellow] would create {counts.created}, "
            f"update {counts.updated}, leave {counts.unchanged} unchanged"
        )
    else:
        console.print(
            f"[green]Done:[/green] created {counts.created}, "
            f"updated {counts.updated}, unchanged {counts.unchanged}"
        )


@click.command()
@click.option("--project-id", help="Filter sections by project ID")
@click.option(
    "--dry-run", is_flag=True, help="Show planned changes without writing to DB"
)
def command(project_id, dry_run):
    """Sync Todoist sections to the TodoistSection model.

    Matches existing records by section_id. Updates name and project_id for
    existing records while preserving the user-set key slug. Creates new records
    with auto-slugified keys derived from the section name.
    """
    console = Console()
    api_token = _get_api_token()

    try:
        api = TodoistAPI(api_token)
        console.print("[green]Fetching Todoist sections...[/green]")
        sections = _fetch_sections(api, project_id)

        if not sections:
            console.print("[yellow]No sections found.[/yellow]")
            return

        existing_keys = set(TodoistSection.objects.values_list("key", flat=True))
        table = _build_results_table()
        counts = SyncCounts()

        for section in sorted(sections, key=lambda s: (s.project_id, s.order)):
            try:
                obj = TodoistSection.objects.get(section_id=section.id)
                result = _sync_existing_section(obj, section, dry_run)
            except TodoistSection.DoesNotExist:
                result = _create_section(section, existing_keys, dry_run)

            counts.created += result.counts.created
            counts.updated += result.counts.updated
            counts.unchanged += result.counts.unchanged
            table.add_row(
                result.status, result.key, section.name, section.id, section.project_id
            )

        console.print(table)
        _print_summary(console, dry_run, counts)

    except Exception as e:
        console.print(f"[red]Error:[/red] {str(e)}", style="bold")
        raise click.Abort()
