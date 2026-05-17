"""repi CLI — entry point for `repi` console script."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
import time
from pathlib import Path

import click
import typer
from rich.console import Console

app = typer.Typer(
    name="repi",
    help="Log ingestion and LLM-based investigation engine.",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_FILE = REPO_ROOT / "db" / "schema.sql"
CONFIG_JSON = REPO_ROOT / "config.json"

PROVIDERS = ["openai", "anthropic", "mistral", "gemini", "ollama"]
PROVIDER_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "gemini": "GEMINI_API_KEY",
}

DEFAULT_DB_URL = "postgresql+asyncpg://lograg_user:password_here@localhost:5432/lograg"
DEFAULT_REDIS_URL = "redis://localhost:6379"


def _env_template(provider: str, api_key: str | None) -> str:
    lines = [
        f"DATABASE_URL={DEFAULT_DB_URL}",
        f"REDIS_URL={DEFAULT_REDIS_URL}",
        f"LLM_PROVIDER={provider}",
    ]
    if api_key and provider in PROVIDER_KEY_ENV:
        lines.append(f"{PROVIDER_KEY_ENV[provider]}={api_key}")
    return "\n".join(lines) + "\n"


def _to_psql_url(db_url: str) -> str:
    return db_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _docker_compose_cmd() -> list[str] | None:
    if shutil.which("docker") is None:
        return None
    try:
        subprocess.run(
            ["docker", "compose", "version"],
            check=True,
            capture_output=True,
        )
        return ["docker", "compose"]
    except (subprocess.CalledProcessError, FileNotFoundError):
        if shutil.which("docker-compose"):
            return ["docker-compose"]
        return None


async def _wait_for_postgres(db_url: str, timeout_s: int = 60) -> bool:
    import asyncpg

    dsn = _to_psql_url(db_url)
    deadline = time.monotonic() + timeout_s
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            conn = await asyncpg.connect(dsn=dsn, timeout=3)
            await conn.close()
            return True
        except Exception as e:
            last_err = e
            await asyncio.sleep(1)
    if last_err:
        console.print(f"[red]Last connection error:[/red] {last_err}")
    return False


async def _apply_schema(db_url: str) -> None:
    import asyncpg

    sql = SCHEMA_FILE.read_text()
    conn = await asyncpg.connect(dsn=_to_psql_url(db_url))
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


def _read_db_url(env_path: Path) -> str:
    if not env_path.exists():
        return DEFAULT_DB_URL
    for line in env_path.read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    return DEFAULT_DB_URL


@app.command()
def init(
    with_docker: bool = typer.Option(
        False, "--with-docker", help="Run `docker compose up -d db redis`."
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite an existing .env file."
    ),
    env_path: Path = typer.Option(
        Path(".env"), "--env-path", help="Where to write the .env file."
    ),
) -> None:
    """Bootstrap repi: write .env, start infra, apply migrations."""
    env_path = env_path.resolve()

    if env_path.exists() and not force:
        console.print(f"[yellow]Existing {env_path} found — keeping it.[/yellow]")
        console.print("[dim]Pass --force to overwrite.[/dim]")
    else:
        provider = typer.prompt(
            "LLM provider",
            default="anthropic",
            type=click.Choice(PROVIDERS, case_sensitive=False),
        ).lower()
        api_key: str | None = None
        if provider in PROVIDER_KEY_ENV:
            api_key = typer.prompt(
                f"{PROVIDER_KEY_ENV[provider]}",
                hide_input=True,
                default="",
                show_default=False,
            ) or None
        env_path.write_text(_env_template(provider, api_key))
        console.print(f"[green]Wrote {env_path}[/green]")

    if CONFIG_JSON.exists():
        console.print(
            f"[yellow]Note:[/yellow] {CONFIG_JSON.name} exists and overrides .env at runtime "
            "(the web UI writes to it via PUT /config). Remove it if you want .env to take effect."
        )

    db_url = _read_db_url(env_path)

    if with_docker:
        cmd = _docker_compose_cmd()
        if cmd is None:
            console.print("[red]docker compose not found on PATH.[/red]")
            raise typer.Exit(code=1)
        console.print("[cyan]Starting db + redis via docker compose...[/cyan]")
        result = subprocess.run(cmd + ["up", "-d", "db", "redis"], cwd=REPO_ROOT)
        if result.returncode != 0:
            console.print("[red]docker compose failed.[/red]")
            raise typer.Exit(code=result.returncode)

    console.print("[cyan]Waiting for Postgres to accept connections...[/cyan]")
    ready = asyncio.run(_wait_for_postgres(db_url))
    if not ready:
        console.print("[red]Postgres did not become ready within 60s.[/red]")
        raise typer.Exit(code=1)
    console.print("[green]Postgres ready.[/green]")

    if not SCHEMA_FILE.exists():
        console.print(f"[red]Schema file not found at {SCHEMA_FILE}.[/red]")
        raise typer.Exit(code=1)
    console.print(f"[cyan]Applying {SCHEMA_FILE.name}...[/cyan]")
    asyncio.run(_apply_schema(db_url))
    console.print("[green]Schema applied.[/green]")

    console.print()
    console.print("[bold green]Setup complete.[/bold green]")
    console.print("Next: [bold]repi serve[/bold] to start the API on http://localhost:8000")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """Start the FastAPI server."""
    import uvicorn

    uvicorn.run("repi.api:app", host=host, port=port, reload=reload)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
