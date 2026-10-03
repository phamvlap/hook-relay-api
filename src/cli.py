"""Hook Relay Management CLI.

Provides administrative commands for managing owners, API keys, and system tasks.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Annotated

# Ensure project root is on sys.path when executed directly as `python src/cli.py`
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.database.session import get_db_context
from src.models.api_key import APIKeyEnvironment
from src.repositories.api_key import APIKeyRepository
from src.repositories.owner import OwnerRepository
from src.schemas.api_key import APIKeyCreateResponse
from src.schemas.owner import OwnerCreateResponse
from src.services.api_key import APIKeyService
from src.services.owner import OwnerService

app = typer.Typer(
    name="hook-relay",
    help="Hook Relay API administrative CLI.",
    no_args_is_help=True,
    add_completion=False,
)
owner_app = typer.Typer(name="owner", help="Manage system owners and access.", no_args_is_help=True)
app.add_typer(owner_app)

console = Console()
err_console = Console(stderr=True)


def _render_owner_and_key(
    owner: OwnerCreateResponse,
    api_key: APIKeyCreateResponse,
    as_json: bool = False,
) -> None:
    """Renders created owner and API key in human-friendly or machine-readable format."""
    if as_json:
        payload = {
            "owner": {
                "id": str(owner.id),
                "created_at": owner.created_at.isoformat() if owner.created_at else None,
            },
            "api_key": {
                "id": str(api_key.id),
                "owner_id": str(api_key.owner_id),
                "key_id": api_key.key_id,
                "name": api_key.name,
                "status": api_key.status.value,
                "environment": api_key.environment.value,
                "api_key": api_key.api_key,
            },
        }
        typer.echo(json.dumps(payload, indent=2))
        return

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="bold cyan")
    table.add_column("Value", style="white")

    env_color = "yellow" if api_key.environment == APIKeyEnvironment.TEST else "red"
    table.add_row("Owner ID", str(owner.id))
    table.add_row("Key ID", api_key.key_id)
    table.add_row("Key Name", api_key.name)
    table.add_row("Environment", f"[{env_color}]{api_key.environment.value.upper()}[/{env_color}]")

    console.print()
    console.print(
        Panel(
            table,
            title="[bold green]Owner & API Key Created Successfully[/bold green]",
        )
    )

    key_panel = Panel(
        f"[bold white]{api_key.api_key}[/bold white]\n\n"
        "[italic yellow]**Please copy and store this API key securely. It will not be shown again.[/italic yellow]",
        title="[bold red]Secret API Key[/bold red]",
        border_style="red",
    )
    console.print(key_panel)
    console.print()


async def _execute_create_owner(
    name: str,
    environment: APIKeyEnvironment,
) -> tuple[OwnerCreateResponse, APIKeyCreateResponse]:
    """Encapsulates the transactional workflow for creating an owner and initial API key."""
    with get_db_context() as session:
        owner_repo = OwnerRepository(session)
        owner_service = OwnerService(owner_repository=owner_repo, session=session)

        api_key_repo = APIKeyRepository(session)
        api_key_service = APIKeyService(api_key_repository=api_key_repo, session=session)

        owner = await owner_service.create()
        api_key = await api_key_service.create(
            owner_id=str(owner.id),
            name=name,
            environment=environment,
        )
        return owner, api_key


def _handle_create_owner(
    name: str,
    env: APIKeyEnvironment,
    as_json: bool,
) -> None:
    """Core handler invoked by create-owner and owner create commands."""
    try:
        owner, api_key = asyncio.run(_execute_create_owner(name=name, environment=env))
        _render_owner_and_key(owner, api_key, as_json=as_json)
    except Exception as exc:
        if as_json:
            typer.echo(json.dumps({"error": str(exc)}), file=sys.stderr)
        else:
            err_console.print(f"[bold red]Error:[/bold red] Failed to create owner: {exc}")
        raise typer.Exit(code=1) from exc


@app.command("create-owner", help="Create a new owner and issue their initial API key.")
def create_owner_cmd(
    name: Annotated[
        str,
        typer.Option(
            "--name",
            "-n",
            help="Name for the initial API key.",
            show_default=False,
        ),
    ],
    env: Annotated[
        APIKeyEnvironment,
        typer.Option(
            "--env",
            "-e",
            help="Environment for the API key (test or live).",
            case_sensitive=False,
        ),
    ] = APIKeyEnvironment.TEST,
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output machine-readable JSON for automation / CI/CD scripts.",
        ),
    ] = False,
) -> None:
    _handle_create_owner(name=name, env=env, as_json=as_json)


@owner_app.command("create", help="Create a new owner and issue their initial API key.")
def owner_create_sub_cmd(
    name: Annotated[
        str,
        typer.Option(
            "--name",
            "-n",
            help="Name for the initial API key.",
            show_default=False,
        ),
    ],
    env: Annotated[
        APIKeyEnvironment,
        typer.Option(
            "--env",
            "-e",
            help="Environment for the API key (test or live).",
            case_sensitive=False,
        ),
    ] = APIKeyEnvironment.TEST,
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output machine-readable JSON for automation / CI/CD scripts.",
        ),
    ] = False,
) -> None:
    _handle_create_owner(name=name, env=env, as_json=as_json)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
