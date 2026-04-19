from .types import DiffHunk, SeedNode
from impact_engine.graph.store import GraphStore

def map_hunks_to_nodes(store: GraphStore, hunks: list[DiffHunk]) -> list[SeedNode]:
    """
    Query Kuzu to find CodeNodes that overlap with the provided DiffHunks.
    """
    seed_nodes = []
    seen_ids = set()
    
    # Kuzu query for interval overlap:
    # node.start_line <= hunk.end_line AND node.end_line >= hunk.start_line
    query = """
    MATCH (n:CodeNode)
    WHERE n.file = $file
      AND n.start_line <= $hunk_end
      AND n.end_line >= $hunk_start
    RETURN n.*
    """
    
    for hunk in hunks:
        results = store.conn.execute(query, {
            "file": hunk.file,
            "hunk_start": hunk.start_line,
            "hunk_end": hunk.end_line
        })
        
        while results.has_next():
            node_data = results.get_next()
            # Convert dict/list results to SeedNode
            # results.get_next() in newer Kuzu returns a list usually if returning *
            # Or a dict if using newer API. Let's assume dict for now given current experience.
            
            # Reconstruct CodeNode fields
            node_id = node_data[0] # Typical Kuzu result format if not using named columns
            if node_id in seen_ids:
                continue
            
            # Since CodeNode is large, we might want to fetch all fields properly
            # In our store.py, we have a schema. Let's map it.
            # Fields: id, file, type, name, start_line, end_line, parent_class, exported, snippet
            
            seed = SeedNode(
                id=node_data[0],
                file=node_data[1],
                type=node_data[2],
                name=node_data[3],
                start_line=node_data[4],
                end_line=node_data[5],
                parent_class=node_data[6],
                exported=node_data[7],
                snippet=node_data[8],
                change_type=hunk.change_type
            )
            # Find specific changed lines within this node
            node_range = range(seed.start_line, seed.end_line + 1)
            hunk_range = range(hunk.start_line, hunk.end_line + 1)
            seed.changed_lines = sorted(list(set(node_range) & set(hunk_range)))
            
            seed_nodes.append(seed)
            seen_ids.add(seed.id)
            
    return seed_nodes
