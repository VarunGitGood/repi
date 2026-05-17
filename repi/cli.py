"""repi CLI — entry point for `repi` console script."""

from __future__ import annotations

import asyncio
import json
import os
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
CONFIG_DIR = REPO_ROOT / ".repi"
CONFIG_FILE = CONFIG_DIR / "config.json"

PROVIDERS = ["openai", "anthropic", "mistral", "gemini", "ollama"]
PROVIDER_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "gemini": "GEMINI_API_KEY",
}

DEFAULT_DB_URL = "postgresql+asyncpg://lograg_user:password_here@localhost:5432/lograg"
DEFAULT_REDIS_URL = "redis://localhost:6379"


def _is_prod() -> bool:
    # Shell env var wins (for one-off overrides / CI). Fall back to .repi/config.json.
    env = os.environ.get("REPI_ENV")
    if env is None:
        try:
            data = json.loads(CONFIG_FILE.read_text())
            env = data.get("REPI_ENV", "production")
        except (OSError, json.JSONDecodeError):
            env = "production"
    return str(env).lower() != "development"


def _setup_logging() -> None:
    import logging

    prod = _is_prod()
    level = logging.WARNING if prod else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    if prod:
        # Third-party libraries that set their own logger level via setLevel
        # need to be quieted explicitly — basicConfig only affects loggers
        # without an explicit level.
        for name in ("sentence_transformers", "httpx", "asyncio"):
            logging.getLogger(name).setLevel(logging.WARNING)


def _config_payload(provider: str, api_key: str | None) -> dict:
    payload: dict = {
        "REPI_ENV": "production",
        "DATABASE_URL": DEFAULT_DB_URL,
        "REDIS_URL": DEFAULT_REDIS_URL,
        "LLM_PROVIDER": provider,
    }
    if api_key and provider in PROVIDER_KEY_ENV:
        payload[PROVIDER_KEY_ENV[provider]] = api_key
    return payload


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


def _read_db_url() -> str:
    if not CONFIG_FILE.exists():
        return DEFAULT_DB_URL
    try:
        data = json.loads(CONFIG_FILE.read_text())
        return data.get("DATABASE_URL", DEFAULT_DB_URL)
    except (OSError, json.JSONDecodeError):
        return DEFAULT_DB_URL


@app.command()
def init(
    with_docker: bool = typer.Option(
        False, "--with-docker", help="Run `docker compose up -d db redis`."
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite an existing .repi/config.json."
    ),
) -> None:
    """Bootstrap repi: write .repi/config.json, start infra, apply migrations."""
    if CONFIG_FILE.exists() and not force:
        console.print(f"[yellow]Existing {CONFIG_FILE.relative_to(REPO_ROOT)} found — keeping it.[/yellow]")
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

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps(_config_payload(provider, api_key), indent=2) + "\n"
        )
        console.print(f"[green]Wrote {CONFIG_FILE.relative_to(REPO_ROOT)}[/green]")

    db_url = _read_db_url()

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
    console.print("Next:")
    console.print("  • [bold]repi serve[/bold] — start the API on http://localhost:8000")
    console.print("  • [bold]repi ui[/bold]    — start the web UI on http://localhost:3000")
    console.print("  • [bold]repi stop[/bold]  — tear down the docker stack when you're done")


@app.command()
def stop(
    volumes: bool = typer.Option(
        False,
        "--volumes",
        "-v",
        help="Also remove the Postgres volume (DESTROYS ingested data).",
    ),
) -> None:
    """Stop the docker stack (db + redis, and api/worker if running)."""
    cmd = _docker_compose_cmd()
    if cmd is None:
        console.print("[red]docker compose not found on PATH.[/red]")
        raise typer.Exit(code=1)

    args = cmd + ["down"]
    if volumes:
        console.print("[yellow]--volumes: this will delete the Postgres volume.[/yellow]")
        args.append("-v")

    result = subprocess.run(args, cwd=REPO_ROOT)
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)
    console.print("[green]Stopped.[/green]")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """Start the FastAPI server."""
    import uvicorn

    _setup_logging()
    prod = _is_prod()
    log_level = "warning" if prod else "info"
    # In production, reload is always off regardless of the flag.
    effective_reload = False if prod else reload

    if prod:
        console.print(f"[green]repi serve on http://{host}:{port}[/green]")
    uvicorn.run(
        "repi.api:app",
        host=host,
        port=port,
        reload=effective_reload,
        log_level=log_level,
    )


@app.command()
def ui(
    port: int = typer.Option(
        None,
        "--port",
        "-p",
        help="Port for the UI. Defaults to UI_PORT from config (3000).",
    ),
    build: bool = typer.Option(
        False, "--build", help="Run a Next.js production build instead of dev."
    ),
    install: bool = typer.Option(False, "--install", help="Run `npm install` before starting."),
) -> None:
    """Start the local web UI (Next.js app under web/).

    Wraps `npm run dev` (or `npm run start` with --build). Next.js logs stream
    to stdout as usual — Ctrl+C stops the server.
    """
    if port is None:
        from repi.core.config import settings
        port = settings.UI_PORT

    web_dir = REPO_ROOT / "web"
    if not web_dir.exists():
        console.print(f"[red]Web app not found at {web_dir}.[/red]")
        raise typer.Exit(code=1)

    if shutil.which("npm") is None:
        console.print("[red]npm not found on PATH. Install Node.js first.[/red]")
        raise typer.Exit(code=1)

    node_modules = web_dir / "node_modules"
    if install or not node_modules.exists():
        if not node_modules.exists():
            console.print(f"[yellow]{node_modules.name} missing — running npm install...[/yellow]")
        result = subprocess.run(["npm", "install"], cwd=web_dir)
        if result.returncode != 0:
            raise typer.Exit(code=result.returncode)

    if build:
        console.print("[cyan]Building production bundle...[/cyan]")
        result = subprocess.run(["npm", "run", "build"], cwd=web_dir)
        if result.returncode != 0:
            raise typer.Exit(code=result.returncode)
        cmd = ["npm", "run", "start", "--", "-p", str(port)]
    else:
        cmd = ["npm", "run", "dev", "--", "-p", str(port)]

    url = f"http://localhost:{port}"
    console.print(f"[bold green]repi UI will be available at {url}[/bold green]")

    try:
        result = subprocess.run(cmd, cwd=web_dir)
    except KeyboardInterrupt:
        return
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
