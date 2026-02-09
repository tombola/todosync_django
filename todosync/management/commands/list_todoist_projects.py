import djclick as click
from django.conf import settings
from todoist_api_python.api import TodoistAPI
from rich.console import Console
from rich.table import Table


@click.command()
def command():
    """List all Todoist projects with their IDs"""
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

        # Fetch all projects
        console.print('[green]Fetching Todoist projects...[/green]', style='bold')
        console.print()

        # Get projects from paginator - it returns a list of projects wrapped in a list
        projects_paginator = api.get_projects()
        projects = []
        for page in projects_paginator:
            # Each page is a list of projects
            if isinstance(page, list):
                projects.extend(page)
            else:
                projects.append(page)

        if not projects:
            console.print('[yellow]No projects found.[/yellow]')
            return

        console.print(f'[green]Found {len(projects)} project(s):[/green]', style='bold')
        console.print()

        # Create rich table
        table = Table(show_header=True, header_style='bold cyan')
        table.add_column('ID', style='dim', width=25)
        table.add_column('Name', width=40)
        table.add_column('Color', width=15)
        table.add_column('Favorite', justify='center', width=10)

        # Sort projects by name
        sorted_projects = sorted(projects, key=lambda p: p.name.lower())

        # Add rows to table
        for project in sorted_projects:
            favorite_marker = '★' if project.is_favorite else ''
            table.add_row(
                project.id,
                project.name,
                project.color,
                favorite_marker
            )

        console.print(table)
        console.print()
        console.print(
            '[green]To use a project for task creation, add its ID to the '
            'todoist_project_id field in Wagtail Admin → Settings → Task Sync Settings[/green]'
        )

    except Exception as e:
        console.print(f'[red]Error fetching projects from Todoist:[/red] {str(e)}', style='bold')
        raise click.Abort()
