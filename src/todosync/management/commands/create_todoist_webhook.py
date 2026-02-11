import requests
import djclick as click
from django.conf import settings
from rich.console import Console

TODOIST_WEBHOOKS_URL = "https://api.todoist.com/sync/v9/webhooks"


@click.command()
@click.argument("webhook_url")
@click.argument("event_names", nargs=-1, required=True)
def command(webhook_url, event_names):
    """Create Todoist webhooks for the given event names.

    Requires TODOIST_CLIENT_ID and TODOIST_CLIENT_SECRET from a Todoist app
    created at https://developer.todoist.com/appconsole.html

    WEBHOOK_URL: Your HTTPS endpoint to receive webhook events.

    EVENT_NAMES: Todoist events (e.g. item:added item:updated item:completed item:uncompleted item:deleted)
    """
    console = Console()

    api_token = getattr(settings, "TODOIST_API_TOKEN", None)
    client_id = getattr(settings, "TODOIST_CLIENT_ID", None)
    client_secret = getattr(settings, "TODOIST_CLIENT_SECRET", None)

    if not api_token:
        console.print("[red]Error:[/red] TODOIST_API_TOKEN not configured in settings.", style="bold")
        raise click.Abort()
    if not client_id or not client_secret:
        console.print(
            "[red]Error:[/red] TODOIST_CLIENT_ID and TODOIST_CLIENT_SECRET are required.", style="bold"
        )
        console.print("Create a Todoist app at https://developer.todoist.com/appconsole.html")
        raise click.Abort()

    headers = {"Authorization": f"Bearer {api_token}"}

    for event in event_names:
        response = requests.post(
            TODOIST_WEBHOOKS_URL,
            headers=headers,
            json={
                "client_id": client_id,
                "client_secret": client_secret,
                "event_name": event,
                "url": webhook_url,
            },
        )

        if response.status_code in (200, 201):
            webhook_id = response.json().get("id")
            console.print(f"[green]Webhook created for '{event}' (id: {webhook_id})[/green]")
        else:
            console.print(f"[red]Failed to create webhook for '{event}': {response.status_code} {response.text}[/red]")
