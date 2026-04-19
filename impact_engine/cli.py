import typer
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
import os
import time

from .extractor.analyzer import CodebaseAnalyzer
from .utils.walker import walk_repo
from .graph.builder import GraphBuilder
from .graph.store import GraphStore

# Phase 2 imports
from .diff.parser import parse_diff
from .diff.mapper import map_hunks_to_nodes
from .analysis.blast import compute_blast_radius
from .analysis.scorer import Scorer

app = typer.Typer(help="repi: Codebase Impact Engine")
console = Console()

@app.command()
def scan(
    path: str = typer.Argument(..., help="Path to the repository to scan"),
):
    """
    Scan a repository, extract entities, build and persist the Code Property Graph.
    """
    repo_path = os.path.abspath(path)
    if not os.path.exists(repo_path):
        console.print(f"[red]Error:[/red] Path {repo_path} does not exist.")
        raise typer.Exit(1)

    console.print(f"Scanning repository: [bold blue]{repo_path}[/bold blue]")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        # Walk and Analyze combined
        task_scan = progress.add_task("Scanning and parsing files...", total=None)
        
        analyzer = CodebaseAnalyzer()
        analyses = []
        
        # walk_repo yields (rel_path, source)
        for rel_path, source in walk_repo(repo_path):
            try:
                analysis = analyzer.analyze_file(rel_path, source)
                analyses.append(analysis)
            except Exception as e:
                console.print(f"[yellow]Warn:[/yellow] Could not analyze {rel_path}: {e}")
            
        progress.update(task_scan, completed=True, description=f"Analyzed {len(analyses)} files")
            
        # Build
        task_graph = progress.add_task("Building graph...", total=None)
        builder = GraphBuilder()
        G = builder.build(analyses)
        progress.update(task_graph, completed=True)
        
        # Store
        task_store = progress.add_task(f"Persisting {G.number_of_nodes()} nodes to Kuzu...", total=None)
        store = GraphStore(repo_path)
        store.upsert_graph(G)
        progress.update(task_store, completed=True)

    console.print("[bold green]Scan complete![/bold green]")

@app.command()
def diff(
    path: str = typer.Argument(".", help="Path to the repository"),
    ref: str = typer.Argument("HEAD", help="Git ref to compare against (e.g. main, HEAD~1)"),
):
    """
    Show directly changed CodeNodes in the current diff.
    """
    repo_path = os.path.abspath(path)
    store = GraphStore(repo_path)
    
    hunks = parse_diff(repo_path, ref)
    seeds = map_hunks_to_nodes(store, hunks)
    
    if not seeds:
        console.print("[yellow]No tracked CodeNodes found in the diff.[/yellow]")
        return
        
    table = Table(title=f"Changed nodes ({len(seeds)})")
    table.add_column("Type", style="cyan")
    table.add_column("Node", style="magenta")
    table.add_column("File", style="green")
    table.add_column("Lines", style="yellow")
    
    for seed in seeds:
        lines_str = f"L{seed.start_line}–{seed.end_line}"
        table.add_row(seed.type, seed.name, seed.file, lines_str)
        
    console.print(table)

@app.command()
def impact(
    path: str = typer.Argument(".", help="Path to the repository"),
    ref: str = typer.Argument("HEAD", help="Git ref to compare against"),
    alpha: float = typer.Option(0.4, help="PageRank weight"),
    beta: float = typer.Option(0.4, help="Betweenness weight"),
    gamma: float = typer.Option(0.2, help="Churn weight"),
    max_depth: int = typer.Option(10, help="Max traversal depth"),
    min_risk: float = typer.Option(0.0, help="Minimum risk score to show"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
):
    """
    Full blast radius report with risk scores.
    """
    start_time = time.time()
    repo_path = os.path.abspath(path)
    store = GraphStore(repo_path)
    
    hunks = parse_diff(repo_path, ref)
    seeds = map_hunks_to_nodes(store, hunks)
    
    if not seeds:
        console.print("[yellow]No seed nodes found for impact analysis.[/yellow]")
        return
        
    G = store.load_networkx_graph()
    impacted = compute_blast_radius(G, seeds, max_depth)
    
    scorer = Scorer(repo_path, G)
    scored = scorer.score(impacted, alpha, beta, gamma)
    
    # Filter
    scored = [n for n in scored if n.risk_score >= min_risk]
    
    if json_output:
        import json
        from dataclasses import asdict
        output = {
            "ref": ref,
            "seed_nodes": [asdict(s) for s in seeds],
            "blast_radius": [asdict(n) for n in scored],
            "total_nodes_affected": len(scored),
            "analysis_duration_ms": int((time.time() - start_time) * 1000)
        }
        console.print_json(data=output)
        return

    table = Table(title=f"Impact Report — {ref}")
    table.add_column("Risk", style="bold red")
    table.add_column("Node", style="magenta")
    table.add_column("Type", style="cyan")
    table.add_column("Dist", justify="right")
    table.add_column("BC", justify="right")
    table.add_column("Churn", justify="right")
    
    for node in scored:
        table.add_row(
            f"{node.risk_score:.2f}",
            node.name,
            node.type,
            str(node.distance),
            f"{node.betweenness:.2f}",
            f"{node.churn:.2f}"
        )
        
    console.print(table)
    
    high = len([n for n in scored if n.risk_score > 0.7])
    med = len([n for n in scored if 0.4 <= n.risk_score <= 0.7])
    low = len([n for n in scored if n.risk_score < 0.4])
    
    console.print(f"\n[bold]High risk (>0.7):[/bold] {high} nodes | [bold]Medium (0.4–0.7):[/bold] {med} nodes | [bold]Low:[/bold] {low} nodes")

@app.command()
def nodes(
    path: str = typer.Argument(".", help="Path to the repository"),
    type: str = typer.Option(None, help="Filter by node type"),
    file: str = typer.Option(None, help="Filter by file path"),
):
    """
    List extracted nodes from the persisted graph.
    """
    repo_path = os.path.abspath(path)
    store = GraphStore(repo_path)
    all_nodes = store.get_nodes()
    
    table = Table(title=f"Extracted Nodes ({len(all_nodes)})")
    table.add_column("ID", style="dim")
    table.add_column("Type")
    table.add_column("Name", style="bold")
    table.add_column("File")
    
    for n in all_nodes:
        if type and n['type'] != type: continue
        if file and n['file'] != file: continue
        table.add_row(n['id'], n['type'], n['name'], n['file'])
        
    console.print(table)

@app.command()
def graph(
    path: str = typer.Argument(".", help="Path to the repository"),
):
    """
    Print graph summary statistics.
    """
    repo_path = os.path.abspath(path)
    store = GraphStore(repo_path)
    G = store.load_networkx_graph()
    
    console.print(f"\n[bold]Graph Summary[/bold]")
    console.print(f"Total Nodes: {G.number_of_nodes()}")
    console.print(f"Total Call Edges: {G.number_of_edges()}")
    
    # Find hotspots (most called nodes)
    in_degrees = dict(G.in_degree())
    top_called = sorted(in_degrees.items(), key=lambda x: x[1], reverse=True)[:5]
    
    table = Table(title="Most Called Nodes")
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("In-Degree", justify="right")
    
    for node_id, count in top_called:
        # Check if node exists (might be dangling if not all files were scanned)
        if node_id in G:
            data = G.nodes[node_id]
            table.add_row(data['name'], data['type'], str(count))
        
    console.print(table)

def main():
    app()

if __name__ == "__main__":
    main()
