import djclick as click
import requests
import requests.exceptions
import stamina
from django.conf import settings
from rich.console import Console


def _is_retryable_request_error(exc: Exception) -> bool:
    if isinstance(exc, requests.exceptions.HTTPError):
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    return isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout))


TODOIST_WEBHOOKS_URL = "https://api.todoist.com/sync/v9/webhooks"


@click.command()
@click.argument("webhook_id")
def command(webhook_id):
    """Delete a Todoist webhook by ID.

    Requires TODOIST_CLIENT_ID and TODOIST_CLIENT_SECRET from a Todoist app
    created at https://developer.todoist.com/appconsole.html

    WEBHOOK_ID: The ID of the webhook to delete. Use list_todoist_webhooks to find IDs.
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
        for attempt in stamina.retry_context(on=_is_retryable_request_error):
            with attempt:
                response = requests.delete(
                    f"{TODOIST_WEBHOOKS_URL}/{webhook_id}",
                    headers=headers,
                    params={"client_id": client_id, "client_secret": client_secret},
                )
                response.raise_for_status()
        console.print(f"[green]Webhook {webhook_id} deleted.[/green]")
    except requests.RequestException as e:
        console.print(f"[red]Failed to delete webhook {webhook_id}:[/red] {e}", style="bold")
        raise click.Abort()
