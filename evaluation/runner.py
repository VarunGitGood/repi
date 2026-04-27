import json
import os
import logging
from typing import List, Dict, Any
from tqdm import tqdm
from rich.console import Console
from rich.table import Table

from lograg.ingest.parser import parse_log_line
from lograg.ingest.chunker import chunk_logs
from lograg.core.pipeline import LogRagPipeline
from lograg.storage.db import DatabaseManager
from lograg.llm.analyzer import LLMAnalyzer
from evaluation.metrics import recall_at_k, hit_at_k, mean_reciprocal_rank

console = Console()

def evaluate(mode: str = "rerank", dataset_path: str = "evaluation/dataset.json", log_path: str = "examples/eval_logs.log"):
    """
    Run evaluation on the dataset for the specified mode.
    """
    if not os.path.exists(dataset_path):
        console.print(f"[red]Error: Dataset not found at {dataset_path}[/red]")
        return
    
    if not os.path.exists(log_path):
        console.print(f"[red]Error: Logs not found at {log_path}[/red]")
        return
    
    with open(dataset_path, "r") as f:
        dataset = json.load(f)
        
    with open(log_path, "r") as f:
        raw_logs = f.readlines()
        
    # 1. Prepare pipeline
    # We use dummies where possible to avoid external calls durante evaluation of retrieval
    db_manager = DatabaseManager(":memory:") # Use in-memory DB for eval
    # We don't need a real LLM for retrieval evaluation
    try:
        os.environ["OPENAI_API_KEY"] = "sk-dummy" # Placeholder
        analyzer = LLMAnalyzer()
    except Exception:
        analyzer = None
        
    pipeline = LogRagPipeline(db_manager, analyzer)
    
    # 2. Pre-process logs into chunks (this is common to all queries)
    parsed_logs = [parse_log_line(line) for line in raw_logs]
    chunks = chunk_logs(parsed_logs)
    
    all_preds = []
    all_truths = []
    
    console.print(f"[bold blue]Running Evaluation [Mode: {mode}][/bold blue]")
    
    for item in tqdm(dataset, desc="Evaluating queries"):
        query = item["query"]
        truth = item["relevant_signatures"]
        
        # Run retrieval stage
        preds = pipeline.run_retrieval(query, chunks, mode=mode)
        
        all_preds.append(preds)
        all_truths.append(truth)
        
        # Optional per-query logging for debugging
        logging.debug(f"Query: {query}")
        logging.debug(f"Top 5 Preds: {preds[:5]}")
        logging.debug(f"Truth: {truth}")

    # 3. Compute Metrics
    r5 = sum([recall_at_k(preds, truth, 5) for preds, truth in zip(all_preds, all_truths)]) / len(dataset)
    h5 = sum([hit_at_k(preds, truth, 5) for preds, truth in zip(all_preds, all_truths)]) / len(dataset)
    mrr = mean_reciprocal_rank(all_preds, all_truths)
    
    # 4. Print Results
    table = Table(title=f"Evaluation Results - {mode}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")
    
    table.add_row("Recall@5", f"{r5:.2f}")
    table.add_row("Hit@5", f"{h5:.2f}")
    table.add_row("MRR", f"{mrr:.2f}")
    
    console.print(table)
    
    return {
        "recall@5": r5,
        "hit@5": h5,
        "mrr": mrr
    }
