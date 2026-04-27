import os
import typer
from typing import List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint
import logging
from dotenv import load_dotenv

# Suppress NLTK and LlamaIndex logging globally
logging.getLogger("nltk").setLevel(logging.ERROR)
logging.getLogger("llama_index").setLevel(logging.ERROR)

from lograg.core.pipeline import LogRagPipeline
from lograg.llm.analyzer import LLMAnalyzer
from lograg.storage.db import DatabaseManager
from lograg.core.config import update_env_file, get_config_summary

load_dotenv()

app = typer.Typer(help="LogRag: AI-powered log investigation tool")
console = Console()

# Cache for ingested logs (simple persistent file for demo)
CACHE_FILE = "data/log_cache.json"

def save_cache(logs: List[str]):
    os.makedirs("data", exist_ok=True)
    import json
    with open(CACHE_FILE, "w") as f:
        json.dump(logs, f)

def load_cache() -> List[str]:
    import json
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    return []

@app.command()
def ingest(path: str = typer.Argument(..., help="Path to the log file")):
    """
    Ingest logs from a file and store them locally.
    """
    if not os.path.exists(path):
        console.print(f"[red]Error: File not found at {path}[/red]")
        raise typer.Exit(1)

    try:
        with open(path, "r") as f:
            lines = f.readlines()
        
        save_cache(lines)
        console.print(f"Done. Ingested {len(lines)} logs.")
    except Exception as e:
        console.print(f"[red]Error ingesting logs: {e}[/red]")
        raise typer.Exit(1)

@app.command()
def investigate(query: str = typer.Argument(..., help="The investigation query")):
    """
    Run an AI-powered investigation on the ingested logs.
    """
    logs = load_cache()
    if not logs:
        console.print("[yellow]No logs ingested. Please run 'lograg ingest <path>' first.[/yellow]")
        raise typer.Exit(1)

    db_path = os.getenv("DB_PATH", "data/lograg.db")
    db_manager = DatabaseManager(db_path)
    
    try:
        analyzer = LLMAnalyzer()
    except ValueError as e:
        console.print(f"[red]Error initializing LLM: {e}[/red]")
        raise typer.Exit(1)

    pipeline = LogRagPipeline(db_manager, analyzer)
    
    with console.status("[bold green]Analyzing logs..."):
        result = pipeline.run_investigation(query, logs)

    # Output using rich
    console.print(Panel(
        f"[bold blue]Summary:[/bold blue] {result.summary}\n"
        f"[bold red]Root Cause:[/bold red] {result.root_cause}",
        title=f"LogRag | {result.title}",
        expand=False
    ))

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Property", style="dim")
    table.add_column("Value")
    
    table.add_row("Confidence", f"{result.confidence:.2f}")
    table.add_row("Severity", result.impact.get("severity", "N/A"))
    table.add_row("Affected Services", ", ".join(result.affected_services))
    
    console.print(table)

    console.print("\n[bold]Reproduction Steps:[/bold]")
    for i, step in enumerate(result.reproduction_steps, 1):
        console.print(f"{i}. {step}")

    console.print("\n")
    issue_color = "green" if result.should_create_issue else "yellow"
    issue_text = "YES" if result.should_create_issue else "NO"
    console.print(f"Would create GitHub issue: [{issue_color}][bold]{issue_text}[/bold][/{issue_color}]")

@app.command()
def config():
    """
    Configure LogRag settings and API keys.
    """
    console.print(Panel("[bold green]LogRag Configuration Flow[/bold green]"))
    
    current = get_config_summary()
    rprint(f"Current OpenAI API Key: [yellow]{current['OPENAI_API_KEY'][:10]}...[/yellow]")
    
    api_key = typer.prompt("Enter your OpenAI API Key", default=os.getenv("OPENAI_API_KEY", ""), hide_input=True)
    db_path = typer.prompt("Enter path for SQLite database", default=os.getenv("DB_PATH", "data/lograg.db"))
    
    if api_key:
        update_env_file({
            "OPENAI_API_KEY": api_key,
            "DB_PATH": db_path
        })
        console.print("[green]Configuration updated successfully![/green]")
    else:
        console.print("[red]API Key is required for investigation features.[/red]")

@app.command()
def evaluate(
    mode: str = typer.Option("rerank", help="Mode: bm25, dense, hybrid, rerank"),
    dataset: str = typer.Option("evaluation/dataset.json", help="Path to evaluation dataset"),
    logs: str = typer.Option("examples/eval_logs.log", help="Path to logs for evaluation")
):
    """
    Evaluate retrieval quality metrics.
    """
    from evaluation.runner import evaluate as run_eval
    run_eval(mode=mode, dataset_path=dataset, log_path=logs)

if __name__ == "__main__":
    app()
