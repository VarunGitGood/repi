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


def _get_version() -> str:
    """Resolve the installed package version, with a dev fallback."""
    try:
        from importlib.metadata import version, PackageNotFoundError
        return version("repi")
    except Exception:
        return "0.0.0+unknown"


def _version_callback(value: bool) -> None:
    if value:
        console.print(_get_version())
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Print the repi version and exit.",
    ),
) -> None:
    """repi — log ingestion and LLM-based investigation engine."""

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
    # .repi/config.json is the sole source. Read it directly here so the CLI
    # doesn't depend on the Settings singleton being importable in every
    # subcommand context.
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
    """Return the docker-compose command if available, else None.

    Does NOT check whether the daemon is reachable — use _docker_daemon_up()
    for that, so callers can give a different error message for daemon-down
    vs CLI-missing.
    """
    if shutil.which("docker") is None:
        if shutil.which("docker-compose") is not None:
            return ["docker-compose"]
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


def _docker_daemon_up(compose_cmd: list[str]) -> bool:
    """True if the docker daemon answers — the CLI being present isn't enough."""
    try:
        # `docker info` exits non-zero if it can't reach the daemon. Same socket
        # path the compose plugin uses, so this is a faithful probe.
        result = subprocess.run(
            [compose_cmd[0], "info"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


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
    provider_opt: str = typer.Option(
        None,
        "--provider",
        help=f"Pre-select the LLM provider (one of: {', '.join(PROVIDERS)}). Skips the interactive prompt.",
    ),
    api_key_opt: str = typer.Option(
        None,
        "--api-key",
        help="Pre-supply the provider API key. Skips the interactive prompt. Mutually exclusive with --api-key-stdin.",
    ),
    api_key_stdin: bool = typer.Option(
        False,
        "--api-key-stdin",
        help="Read the provider API key from the first line of stdin. Useful for piping from a secrets manager.",
    ),
) -> None:
    """Bootstrap repi: write .repi/config.json, start infra, apply migrations.

    For unattended / CI use, supply `--provider` and one of `--api-key` /
    `--api-key-stdin` to skip the prompts entirely:

        repi init --provider mistral --api-key sk-... --with-docker
        cat secret | repi init --provider mistral --api-key-stdin --with-docker
    """
    if api_key_opt is not None and api_key_stdin:
        console.print("[red]--api-key and --api-key-stdin are mutually exclusive.[/red]")
        raise typer.Exit(code=2)

    if provider_opt is not None and provider_opt.lower() not in PROVIDERS:
        console.print(
            f"[red]Unknown --provider '{provider_opt}'. Choose one of: {', '.join(PROVIDERS)}.[/red]"
        )
        raise typer.Exit(code=2)

    if CONFIG_FILE.exists() and not force:
        console.print(f"[yellow]Existing {CONFIG_FILE.relative_to(REPO_ROOT)} found — keeping it.[/yellow]")
        console.print("[dim]Pass --force to overwrite.[/dim]")
    else:
        if provider_opt is not None:
            provider = provider_opt.lower()
        else:
            provider = typer.prompt(
                "LLM provider",
                default="anthropic",
                type=click.Choice(PROVIDERS, case_sensitive=False),
            ).lower()

        api_key: str | None = None
        if provider in PROVIDER_KEY_ENV:
            if api_key_opt is not None:
                api_key = api_key_opt or None
            elif api_key_stdin:
                api_key = sys.stdin.readline().strip() or None
                if api_key is None:
                    console.print("[red]--api-key-stdin given but stdin was empty.[/red]")
                    raise typer.Exit(code=2)
            else:
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
            console.print(
                "[dim]Install Docker Desktop or the docker-compose plugin, "
                "then re-run `repi init --with-docker`.[/dim]"
            )
            raise typer.Exit(code=1)
        if not _docker_daemon_up(cmd):
            console.print(
                "[red]Docker CLI found, but the daemon isn't responding.[/red]"
            )
            console.print(
                "[dim]Start Docker Desktop (or `sudo systemctl start docker`) "
                "and try again. Verify with `docker info`.[/dim]"
            )
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
            console.print(
                "[yellow]First-time setup: installing UI dependencies via npm "
                "(~10–30s, only happens once).[/yellow]"
            )
        else:
            console.print("[cyan]Re-running npm install...[/cyan]")
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


config_app = typer.Typer(
    name="config",
    help="Inspect or modify the .repi/config.json file.",
    no_args_is_help=False,
    invoke_without_command=True,
)
app.add_typer(config_app, name="config")


def _is_secret_field(field_name: str) -> bool:
    return field_name.endswith("_API_KEY")


def _mask_secret(value: str | None) -> str:
    if not value:
        return "<unset>"
    s = str(value)
    if len(s) <= 10:
        return "***"
    return f"{s[:4]}…{s[-4:]}"


def _load_config_dict() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (OSError, json.JSONDecodeError) as e:
        console.print(f"[yellow]Could not parse {CONFIG_FILE}: {e}. Starting from defaults.[/yellow]")
        return {}


def _write_validated_config(data: dict) -> None:
    """Validate via Settings and write to CONFIG_FILE — same code path the web UI uses."""
    from repi.core.config import Settings

    validated = Settings(**data)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(validated.model_dump(), indent=2) + "\n")


def _coerce_value(raw: str):
    """Coerce a CLI-supplied string into bool/None/int — strings pass through."""
    low = raw.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("none", "null", ""):
        return None
    try:
        return int(raw)
    except ValueError:
        return raw


@config_app.callback(invoke_without_command=True)
def _config_root(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is not None:
        return
    _run_interactive_config()


def _run_interactive_config() -> None:
    from repi.core.config import Settings, get_settings

    settings = get_settings()
    current = settings.model_dump()
    new_values: dict = dict(current)

    rel = CONFIG_FILE.relative_to(REPO_ROOT) if CONFIG_FILE.is_relative_to(REPO_ROOT) else CONFIG_FILE
    console.print(
        f"[bold]Editing {rel}[/bold] — press Enter to keep the current value.\n"
    )

    for field_name, field_info in Settings.model_fields.items():
        cur = current.get(field_name)
        annotation = field_info.annotation

        if _is_secret_field(field_name):
            shown = _mask_secret(cur)
            entered = typer.prompt(
                f"{field_name} (current: {shown})",
                default="",
                show_default=False,
                hide_input=True,
            )
            if entered:
                new_values[field_name] = entered
            continue

        if annotation is bool:
            new_values[field_name] = typer.confirm(field_name, default=bool(cur))
            continue

        default_val = "" if cur is None else cur
        entered = typer.prompt(field_name, default=default_val, show_default=True)
        if entered == "" and cur is None:
            continue
        new_values[field_name] = entered if entered != "" else None

    try:
        _write_validated_config(new_values)
    except Exception as e:
        console.print(f"[red]Validation failed:[/red] {e}")
        raise typer.Exit(code=1)

    console.print(f"[green]Wrote {rel}.[/green] Restart `repi serve` to pick up changes.")


@config_app.command("get")
def config_get(
    key: str = typer.Argument(..., help="Field name (e.g. LLM_PROVIDER)."),
    unmask: bool = typer.Option(False, "--unmask", help="Show secrets in plaintext."),
) -> None:
    """Print a single config value (masked for *_API_KEY unless --unmask)."""
    from repi.core.config import Settings, get_settings

    if key not in Settings.model_fields:
        console.print(f"[red]Unknown key:[/red] {key}")
        raise typer.Exit(code=1)

    value = getattr(get_settings(), key, None)
    if _is_secret_field(key) and not unmask:
        value = _mask_secret(value)
    console.print("<unset>" if value is None else str(value))


@config_app.command("set")
def config_set(
    pair: str = typer.Argument(..., help="KEY=VALUE expression (e.g. LLM_PROVIDER=anthropic)."),
) -> None:
    """Set a single config value non-interactively."""
    from repi.core.config import Settings

    if "=" not in pair:
        console.print("[red]Expected KEY=VALUE.[/red]")
        raise typer.Exit(code=1)
    key, _, raw = pair.partition("=")
    key = key.strip()
    raw = raw.strip()

    if key not in Settings.model_fields:
        console.print(f"[red]Unknown key:[/red] {key}")
        raise typer.Exit(code=1)

    data = _load_config_dict()
    data[key] = _coerce_value(raw)

    try:
        _write_validated_config(data)
    except Exception as e:
        console.print(f"[red]Validation failed:[/red] {e}")
        raise typer.Exit(code=1)

    shown = "<hidden>" if _is_secret_field(key) else data[key]
    console.print(f"[green]Set {key} = {shown}.[/green] Restart `repi serve` to pick up changes.")


async def _check_postgres(db_url: str) -> tuple[bool, str]:
    try:
        import asyncpg
        conn = await asyncpg.connect(dsn=_to_psql_url(db_url), timeout=3)
        try:
            v = await conn.fetchval("SELECT version()")
        finally:
            await conn.close()
        return True, str(v).split(",")[0] if v else "connected"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


async def _check_pgvector(db_url: str) -> tuple[bool, str]:
    try:
        import asyncpg
        conn = await asyncpg.connect(dsn=_to_psql_url(db_url), timeout=3)
        try:
            row = await conn.fetchrow(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            )
        finally:
            await conn.close()
        if row is None:
            return False, "extension not installed (run `CREATE EXTENSION vector`)"
        return True, f"vector {row['extversion']}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


async def _check_redis(url: str) -> tuple[bool, str]:
    try:
        import redis.asyncio as redis_async
        client = redis_async.from_url(url, socket_connect_timeout=3)
        try:
            pong = await client.ping()
        finally:
            await client.close()
        return bool(pong), f"PING {'ok' if pong else 'failed'}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _check_llm_key(settings) -> tuple[bool, str]:
    provider = (settings.LLM_PROVIDER or "").lower()
    key_field_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }
    if provider == "ollama":
        return True, "ollama (no key required)"
    field = key_field_map.get(provider)
    if field is None:
        return False, f"unknown provider '{provider}'"
    val = getattr(settings, field, None) or getattr(settings, "LLM_API_KEY", None)
    if not val:
        return False, f"{field} not set"
    masked = f"{val[:4]}…{val[-4:]}" if len(val) > 10 else "set"
    return True, masked


def _check_embedding() -> tuple[bool, str]:
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        vec = model.encode("ok")
        return True, f"all-MiniLM-L6-v2, dim={len(vec)}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


@app.command()
def doctor(
    skip_embedding: bool = typer.Option(
        False,
        "--skip-embedding",
        help="Skip the SentenceTransformer round-trip (faster, network-free).",
    ),
) -> None:
    """Run health checks against Python, Postgres, pgvector, Redis, LLM key, and embeddings."""
    from rich.table import Table
    from repi.core.config import settings

    checks: list[tuple[str, bool, str]] = []

    py = sys.version_info
    checks.append(
        ("Python >= 3.11", py >= (3, 11), f"{py.major}.{py.minor}.{py.micro}")
    )

    if CONFIG_FILE.exists():
        checks.append((".repi/config.json present", True, str(CONFIG_FILE.relative_to(REPO_ROOT))))
    else:
        checks.append(
            (".repi/config.json present", False, "missing — run `repi init`")
        )

    db_url = _read_db_url()
    pg_ok, pg_detail = asyncio.run(_check_postgres(db_url))
    checks.append(("Postgres reachable", pg_ok, pg_detail))

    if pg_ok:
        v_ok, v_detail = asyncio.run(_check_pgvector(db_url))
    else:
        v_ok, v_detail = False, "skipped (Postgres unreachable)"
    checks.append(("pgvector extension", v_ok, v_detail))

    if settings.ENABLE_REDIS_CACHE:
        r_ok, r_detail = asyncio.run(_check_redis(settings.REDIS_URL))
        checks.append(("Redis reachable", r_ok, r_detail))
    else:
        checks.append(("Redis reachable", True, "disabled (ENABLE_REDIS_CACHE=false)"))

    k_ok, k_detail = _check_llm_key(settings)
    checks.append((f"LLM key ({settings.LLM_PROVIDER})", k_ok, k_detail))

    if skip_embedding:
        checks.append(("Embedding round-trip", True, "skipped (--skip-embedding)"))
    else:
        e_ok, e_detail = _check_embedding()
        checks.append(("Embedding round-trip", e_ok, e_detail))

    table = Table(title=f"repi doctor — v{_get_version()}", show_lines=False)
    table.add_column("Check", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Detail", overflow="fold")
    for name, ok, detail in checks:
        status = "[green]PASS[/green]" if ok else "[red]FAIL[/red]"
        table.add_row(name, status, detail)
    console.print(table)

    if not all(ok for _, ok, _ in checks):
        raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
