import requests
import djclick as click
from django.conf import settings
from rich.console import Console
from rich.table import Table

TODOIST_WEBHOOKS_URL = "https://api.todoist.com/sync/v9/webhooks"


@click.command()
def command():
    """List all Todoist webhooks.

    Requires TODOIST_CLIENT_ID and TODOIST_CLIENT_SECRET from a Todoist app
    created at https://developer.todoist.com/appconsole.html
    """
    console = Console()

    api_token = getattr(settings, "TODOIST_API_TOKEN", None)
    client_id = getattr(settings, "TODOIST_CLIENT_ID", None)
    client_secret = getattr(settings, "TODOIST_CLIENT_SECRET", None)

    if not api_token:
        console.print("[red]Error:[/red] TODOIST_API_TOKEN not configured in settings.", style="bold")
        raise click.Abort()
    if not client_id or not client_secret:
        console.print("[red]Error:[/red] TODOIST_CLIENT_ID and TODOIST_CLIENT_SECRET are required.", style="bold")
        console.print("Create a Todoist app at https://developer.todoist.com/appconsole.html")
        raise click.Abort()

    headers = {"Authorization": f"Bearer {api_token}"}

    try:
        response = requests.get(
            TODOIST_WEBHOOKS_URL,
            headers=headers,
            params={"client_id": client_id, "client_secret": client_secret},
        )
        response.raise_for_status()
    except requests.RequestException as e:
        console.print(f"[red]Error fetching webhooks:[/red] {e}", style="bold")
        raise click.Abort()

    webhooks = response.json()

    if not webhooks:
        console.print("[yellow]No webhooks found.[/yellow]")
        return

    console.print(f"[green]Found {len(webhooks)} webhook(s):[/green]", style="bold")
    console.print()

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", width=15)
    table.add_column("Event", width=25)
    table.add_column("URL", width=60)

    for wh in sorted(webhooks, key=lambda w: w.get("event_name", "")):
        table.add_row(
            str(wh.get("id", "")),
            wh.get("event_name", ""),
            wh.get("url", ""),
        )

    console.print(table)
