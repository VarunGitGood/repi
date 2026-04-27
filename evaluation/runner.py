import json
import asyncio
import argparse
import os
from typing import List, Dict, Any
from tqdm import tqdm
from rich.console import Console
from rich.table import Table

from src.app.core.container import Container
from evaluation.metrics import recall_at_k, hit_at_k, mean_reciprocal_rank

console = Console()

class EvaluationRunner:
    def __init__(self, container: Container):
        self.container = container
        self.dataset = []
        
    def load_dataset(self, path: str):
        with open(path, "r") as f:
            self.dataset = json.load(f)
        console.print(f"Loaded {len(self.dataset)} queries from dataset.")

    async def prepare_logs(self, log_path: str):
        """Ingest logs from file into the database."""
        if not os.path.exists(log_path):
            console.print(f"[red]Error: Logs not found at {log_path}[/red]")
            return

        with open(log_path, "r") as f:
            logs_content = f.read()

        async with self.container.async_session_maker() as session:
            ingestor = self.container.get_ingestor(session)
            # Use a dummy source for eval logs
            await ingestor.ingest(logs_content, source_service="eval-mock", source_env="evaluation")
            await session.commit()
        console.print(f"Ingested logs from {log_path} into database.")

    async def run_eval(self, top_k: int = 5, recency_boost: bool = False):
        all_preds = []
        all_truths = []
        
        async with self.container.async_session_maker() as session:
            retrieval_service = self.container.get_retrieval_service(session)
            
            for item in tqdm(self.dataset, desc="Evaluating"):
                query = item["query"]
                truth = item["relevant_signatures"]
                
                # Perform search
                results = await retrieval_service.search(
                    query=query, 
                    top_k=top_k, 
                    recency_boost=recency_boost
                )
                
                # Extract chunk IDs (which are signatures in our system)
                preds = [res[0] for res in results]
                
                all_preds.append(preds)
                all_truths.append(truth)

        return self.compute_metrics(all_preds, all_truths, top_k)

    def compute_metrics(self, all_preds, all_truths, k: int):
        r_k = sum([recall_at_k(p, t, k) for p, t in zip(all_preds, all_truths)]) / len(all_preds)
        h_k = sum([hit_at_k(p, t, k) for p, t in zip(all_preds, all_truths)]) / len(all_preds)
        mrr = mean_reciprocal_rank(all_preds, all_truths)
        
        return {
            f"Recall@{k}": r_k,
            f"Hit@{k}": h_k,
            "MRR": mrr
        }

    def display_results(self, metrics: Dict[str, float]):
        table = Table(title="Evaluation Results")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="magenta")
        
        for k, v in metrics.items():
            table.add_row(k, f"{v:.4f}")
        
        console.print(table)

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="evaluation/dataset.json")
    parser.add_argument("--logs", default="examples/eval_logs.log")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--boost", action="store_true")
    args = parser.parse_args()

    # Ensure absolute path for logs if needed, but here relative is fine if run from root
    import os
    
    container = Container()
    # We might need to init DB if running first time or in mock env
    # await container.init_db() 

    runner = EvaluationRunner(container)
    runner.load_dataset(args.dataset)
    
    # Optional: Clear eval logs first or just ingest (chunk_id is signature, so it's idempotent-ish)
    await runner.prepare_logs(args.logs)
    
    metrics = await runner.run_eval(top_k=args.top_k, recency_boost=args.boost)
    runner.display_results(metrics)

if __name__ == "__main__":
    asyncio.run(main())
