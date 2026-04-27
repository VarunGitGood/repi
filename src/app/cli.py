from __future__ import annotations
import asyncio
import typer
from rich.console import Console
from rich.table import Table
from src.app.core.container import Container
from src.app.intent.basic_parser import parse_intent
from src.app.models.filters import RetrievalFilters

app = typer.Typer()
console = Console()
container = Container()

@app.command()
def query(text: str):
    """Query logs with natural language intent."""
    async def _run():
        await container.init_db()
        await container.init_known_services()
        
        # 1. Parse Intent
        intent = parse_intent(text, container.known_services)
        console.print(f"[bold blue]Intent Parsed:[/bold blue]")
        console.print(f"  Service: {intent.source_service}")
        console.print(f"  Level: {intent.log_level}")
        console.print(f"  Time Range: {intent.time_from} to {intent.time_to}")
        console.print(f"  Clean Query: {intent.clean_query}")
        
        # 2. Build Filters
        filters = RetrievalFilters(
            source_service=intent.source_service,
            source_env=None, # Default to None to not restrict unless specified
            log_level=intent.log_level,
            time_from=intent.time_from,
            time_to=intent.time_to
        )
        
        # 3. Search
        async with container.async_session_maker() as session:
            retrieval_service = container.get_retrieval_service(session)
            results = await retrieval_service.search(
                query=intent.clean_query,
                top_k=5,
                filters=filters,
                recency_boost=True
            )
            
            # 4. Display Results
            table = Table(title=f"Results for: {text}")
            table.add_column("Chunk ID", style="cyan")
            table.add_column("Score", style="magenta")
            
            for chunk_id, score in results:
                table.add_row(chunk_id, f"{score:.4f}")
            
            console.print(table)

    asyncio.run(_run())

@app.command()
def status():
    """Check database status."""
    console.print("[green]System is online.[/green]")
    console.print(f"Database: {container.db_url}")

if __name__ == "__main__":
    app()
