import djclick as click
from django.conf import settings
from todoist_api_python.api import TodoistAPI
from rich.console import Console
from rich.table import Table


@click.command()
@click.option('--project-id', help='Filter sections by project ID')
def command(project_id):
    """List all Todoist sections with their IDs"""
    console = Console()

    # Get API token from settings
    api_token = getattr(settings, 'TODOIST_API_TOKEN', None)

    if not api_token:
        console.print(
            '[red]Error:[/red] TODOIST_API_TOKEN not configured in settings.',
            style='bold'
        )
        console.print('Please add your Todoist API token to the .env file.')
        raise click.Abort()

    try:
        # Initialize Todoist API
        api = TodoistAPI(api_token)

        # Fetch all sections
        console.print('[green]Fetching Todoist sections...[/green]', style='bold')
        console.print()

        # Get sections from paginator
        sections_paginator = api.get_sections(project_id=project_id) if project_id else api.get_sections()
        sections = []
        for page in sections_paginator:
            # Each page is a list of sections
            if isinstance(page, list):
                sections.extend(page)
            else:
                sections.append(page)

        if not sections:
            if project_id:
                console.print(f'[yellow]No sections found for project {project_id}.[/yellow]')
            else:
                console.print('[yellow]No sections found.[/yellow]')
            return

        console.print(f'[green]Found {len(sections)} section(s):[/green]', style='bold')
        console.print()

        # Create rich table
        table = Table(show_header=True, header_style='bold cyan')
        table.add_column('ID', style='dim', width=25)
        table.add_column('Name', width=40)
        table.add_column('Project ID', width=25)
        table.add_column('Order', justify='right', width=10)

        # Sort sections by project_id, then order
        sorted_sections = sorted(sections, key=lambda s: (s.project_id, s.order))

        # Add rows to table
        for section in sorted_sections:
            table.add_row(
                section.id,
                section.name,
                section.project_id,
                str(section.order)
            )

        console.print(table)
        console.print()
        console.print(
            '[green]To use a section for label rules, add its ID to the '
            'Label Action Rules in Wagtail Admin → Settings → Task Sync Settings[/green]'
        )

    except Exception as e:
        console.print(f'[red]Error fetching sections from Todoist:[/red] {str(e)}', style='bold')
        raise click.Abort()
