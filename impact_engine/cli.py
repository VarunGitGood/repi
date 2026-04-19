import os
import json
import typer
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from impact_engine.utils.walker import walk_repo
from impact_engine.extractor.analyzer import CodebaseAnalyzer
from impact_engine.graph.builder import build_graph
from impact_engine.graph.store import GraphStore

app = typer.Typer(help="repi: Codebase Impact Engine")
console = Console()

@app.command()
def scan(
    path: str = typer.Argument(".", help="Path to the repository to scan"),
    json_out: bool = typer.Option(False, "--json", help="Output results in JSON format")
):
    """Scan a repository, extract entities, build and persist the Code Property Graph."""
    repo_path = os.path.abspath(path)
    
    if not json_out:
        console.print(f"[bold blue]Scanning repository:[/bold blue] {repo_path}")
        
    analyzer = CodebaseAnalyzer()
    analyses = []
    
    files_to_scan = list(walk_repo(repo_path))
    
    if not json_out:
        with Progress() as progress:
            task = progress.add_task("[green]Parsing files...[/green]", total=len(files_to_scan))
            for rel_file, source in files_to_scan:
                analysis = analyzer.analyze_file(rel_file, source)
                analyses.append(analysis)
                progress.advance(task)
    else:
        for rel_file, source in files_to_scan:
            analysis = analyzer.analyze_file(rel_file, source)
            analyses.append(analysis)

    if not json_out:
        console.print("[bold blue]Building graph...[/bold blue]")
    G = build_graph(analyses)
    total_nodes = G.number_of_nodes()
    total_edges = G.number_of_edges()
    
    if not json_out:
        console.print(f"[bold blue]Persisting {total_nodes} nodes and {total_edges} edges to Kuzu...[/bold blue]")
    store = GraphStore(repo_path)
    store.upsert_graph(G)
    
    if json_out:
        console.print(json.dumps({"nodes": total_nodes, "edges": total_edges, "status": "success"}))
    else:
        console.print("[bold green]Scan complete![/bold green]")

@app.command()
def nodes(
    path: str = typer.Argument(".", help="Path to the repository"),
    type: str = typer.Option(None, "--type", "-t", help="Filter by node type"),
    file: str = typer.Option(None, "--file", "-f", help="Filter by file path"),
    json_out: bool = typer.Option(False, "--json", help="Output in JSON format")
):
    """List extracted nodes from the persisted graph."""
    repo_path = os.path.abspath(path)
    store = GraphStore(repo_path)
    
    query = "MATCH (n:CodeNode) "
    conditions = []
    if type:
        conditions.append(f"n.type = '{type}'")
    if file:
        conditions.append(f"n.file = '{file}'")
        
    if conditions:
        query += "WHERE " + " AND ".join(conditions) + " "
        
    query += "RETURN n.id, n.file, n.type, n.name, n.start_line, n.parent_class"
    
    results = store.conn.execute(query)
    
    nodes_list = []
    while results.has_next():
        row = results.get_next()
        nodes_list.append({
            "id": row[0],
            "file": row[1],
            "type": row[2],
            "name": row[3],
            "start_line": row[4],
            "parent_class": row[5]
        })
        
    if json_out:
        console.print(json.dumps(nodes_list, indent=2))
    else:
        table = Table(title="Code Nodes")
        table.add_column("ID", style="cyan")
        table.add_column("Type", style="magenta")
        table.add_column("Name", style="green")
        table.add_column("File", style="blue")
        table.add_column("Line", style="yellow")
        
        for n in nodes_list:
            table.add_row(n['id'], n['type'], n['name'] if not n['parent_class'] else f"{n['parent_class']}.{n['name']}", n['file'], str(n['start_line']))
            
        console.print(table)

@app.command()
def graph(
    path: str = typer.Argument(".", help="Path to the repository"),
    json_out: bool = typer.Option(False, "--json", help="Output in JSON format")
):
    """Print graph summary statistics."""
    repo_path = os.path.abspath(path)
    store = GraphStore(repo_path)
    
    node_count = store.conn.execute("MATCH (n:CodeNode) RETURN count(n)").get_next()[0]
    edge_count = store.conn.execute("MATCH (a)-[r:CallEdge]->(b) RETURN count(r)").get_next()[0]
    
    top_query = """
    MATCH (a:CodeNode)-[r:CallEdge]->(b:CodeNode)
    RETURN b.name, b.type, count(r) AS in_degree
    ORDER BY in_degree DESC LIMIT 5
    """
    results = store.conn.execute(top_query)
    top_nodes = []
    while results.has_next():
        row = results.get_next()
        top_nodes.append({"name": row[0], "type": row[1], "in_degree": row[2]})
        
    if json_out:
        console.print(json.dumps({
            "nodes": node_count,
            "edges": edge_count,
            "top_nodes": top_nodes
        }, indent=2))
    else:
        console.print(f"[bold cyan]Graph Summary[/bold cyan]")
        console.print(f"Total Nodes: {node_count}")
        console.print(f"Total Call Edges: {edge_count}")
        
        table = Table(title="Most Called Nodes")
        table.add_column("Name", style="green")
        table.add_column("Type", style="magenta")
        table.add_column("In-Degree", style="yellow", justify="right")
        
        for n in top_nodes:
            table.add_row(n['name'], n['type'], str(n['in_degree']))
            
        console.print(table)

if __name__ == "__main__":
    app()
