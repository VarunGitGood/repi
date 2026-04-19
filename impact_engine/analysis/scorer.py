import os
import json
import networkx as nx
from git import Repo
from ..diff.types import ImpactedNode

class Scorer:
    def __init__(self, repo_path: str, G: nx.DiGraph):
        self.repo_path = repo_path
        self.G = G
        self.metrics_path = os.path.join(repo_path, ".repi", "metrics.json")
        
    def _get_churn(self) -> dict[str, float]:
        """
        Calculate commit churn for each file in the last 90 days.
        """
        repo = Repo(self.repo_path)
        file_to_churn = {}
        all_files = set(nx.get_node_attributes(self.G, 'file').values())
        
        for file_path in all_files:
            try:
                # Count commits touching this file
                commits = list(repo.iter_commits(paths=file_path, since="90 days ago"))
                file_to_churn[file_path] = len(commits)
            except:
                file_to_churn[file_path] = 0
                
        if not file_to_churn:
            return {f: 0.0 for f in all_files}
            
        max_churn = max(file_to_churn.values()) if file_to_churn.values() else 1
        return {f: c / max_churn for f, c in file_to_churn.items()}

    def _get_centrality(self) -> tuple[dict, dict]:
        """
        Calculate PageRank and Betweenness Centrality. Uses cache if valid.
        """
        if os.path.exists(self.metrics_path):
            with open(self.metrics_path, 'r') as f:
                cache = json.load(f)
                if cache.get("node_count") == self.G.number_of_nodes():
                    return cache["pagerank"], cache["betweenness"]
        
        # Calculate
        pr = nx.pagerank(self.G)
        # Betweenness is expensive
        bc = nx.betweenness_centrality(self.G, normalized=True)
        
        # Cache
        with open(self.metrics_path, 'w') as f:
            json.dump({
                "node_count": self.G.number_of_nodes(),
                "pagerank": pr,
                "betweenness": bc
            }, f)
            
        return pr, bc

    def score(self, nodes: list[ImpactedNode], alpha=0.4, beta=0.4, gamma=0.2) -> list[ImpactedNode]:
        pr_map, bc_map = self._get_centrality()
        churn_map = self._get_churn()
        
        # Normalise PR across the current graph for the score
        max_pr = max(pr_map.values()) if pr_map.values() else 1
        
        for node in nodes:
            node.pagerank = pr_map.get(node.id, 0) / max_pr
            node.betweenness = bc_map.get(node.id, 0)
            node.churn = churn_map.get(node.file, 0)
            
            # Risk(u) = α·PR + β·BC + γ·Churn
            node.risk_score = (alpha * node.pagerank) + (beta * node.betweenness) + (gamma * node.churn)
            
        return sorted(nodes, key=lambda x: x.risk_score, reverse=True)
