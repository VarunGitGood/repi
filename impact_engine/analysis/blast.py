import collections
import networkx as nx
from ..diff.types import SeedNode, ImpactedNode

def compute_blast_radius(G: nx.DiGraph, seed_nodes: list[SeedNode], max_depth: int = 10) -> list[ImpactedNode]:
    """
    Perform BFS forward traversal from seed nodes to find all downstream impacted nodes.
    """
    impacted = {}
    
    # Initialize BFS queue with seeds at distance 0
    # Queue stores (node_id, distance, path)
    queue = collections.deque()
    for seed in seed_nodes:
        if seed.id in G:
            queue.append((seed.id, 0, [seed.id]))
            # Seed nodes also go into the impacted set as distance 0
            if seed.id not in impacted:
                node_data = G.nodes[seed.id]
                impacted[seed.id] = ImpactedNode(
                    id=seed.id,
                    file=node_data['file'],
                    type=node_data['type'],
                    name=node_data['name'],
                    start_line=node_data['start_line'],
                    end_line=node_data['end_line'],
                    parent_class=node_data['parent_class'],
                    exported=node_data['exported'],
                    snippet=node_data['snippet'],
                    distance=0,
                    path_from_seed=[seed.id]
                )

    # Note: store.py schema uses end_line, not end_point. Checking...
    # Actually, I used end_line in my replacement call.
    
    visited = {seed.id for seed in seed_nodes if seed.id in G}
    
    while queue:
        u_id, dist, path = queue.popleft()
        
        if dist >= max_depth:
            continue
            
        # Forward traversal (who calls me? no, who do I affect?)
        # Edges are (caller) -> (callee)
        # Blast radius is: if a callee changes, who is the caller? 
        # So we need to traverse BACKWARDS along the CALLS edges.
        
        # Wait, the prompt says "BFS forward traversal on networkx graph".
        # If A calls B, and B changes, A is impacted. 
        # This means we traverse from B to A (predecessors in DiGraph).
        
        for v_id in G.predecessors(u_id):
            if v_id not in visited:
                visited.add(v_id)
                node_data = G.nodes[v_id]
                impacted[v_id] = ImpactedNode(
                    id=v_id,
                    file=node_data['file'],
                    type=node_data['type'],
                    name=node_data['name'],
                    start_line=node_data['start_line'],
                    end_line=node_data['end_line'],
                    parent_class=node_data['parent_class'],
                    exported=node_data['exported'],
                    snippet=node_data['snippet'],
                    distance=dist + 1,
                    path_from_seed=path + [v_id]
                )
                queue.append((v_id, dist + 1, path + [v_id]))
                
    # Return nodes sorted by distance, excluding seeds (optional, but prompt says mark seeds as 0)
    return list(impacted.values())
