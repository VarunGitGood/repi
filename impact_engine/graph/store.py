import kuzu
import os
import networkx as nx

class GraphStore:
    def __init__(self, repo_path: str):
        db_path = os.path.join(repo_path, '.repi', 'graph.kuzu')
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db = kuzu.Database(db_path)
        self.conn = kuzu.Connection(self.db)
        self._init_schema()

    def _init_schema(self):
        try:
            self.conn.execute("CREATE NODE TABLE CodeNode (id STRING, file STRING, type STRING, name STRING, start_line INT64, end_line INT64, parent_class STRING, exported BOOLEAN, snippet STRING, PRIMARY KEY (id))")
        except RuntimeError:
            pass
            
        try:
            self.conn.execute("CREATE REL TABLE CallEdge (FROM CodeNode TO CodeNode)")
        except RuntimeError:
            pass

    def upsert_graph(self, G: nx.DiGraph):
        for node_id, data in G.nodes(data=True):
            if 'type' not in data:
                continue
            parent_class = data.get('parent_class') or ""
            query = """
                MERGE (n:CodeNode {id: $id})
                SET n.file = $file, n.type = $type, n.name = $name, n.start_line = $start_line, 
                    n.end_line = $end_line, n.parent_class = $parent_class, n.exported = $exported, 
                    n.snippet = $snippet
            """
            params = {
                'id': data.get('id', ''),
                'file': data.get('file', ''),
                'type': data.get('type', ''),
                'name': data.get('name', ''),
                'start_line': data.get('start_line', 0),
                'end_line': data.get('end_line', 0),
                'parent_class': parent_class,
                'exported': data.get('exported', False),
                'snippet': data.get('snippet', '')
            }
            self.conn.execute(query, params)

        for u, v, data in G.edges(data=True):
            if data.get('type') == 'calls':
                query = """
                    MATCH (a:CodeNode {id: $u}), (b:CodeNode {id: $v})
                    MERGE (a)-[r:CallEdge]->(b)
                """
                self.conn.execute(query, {'u': u, 'v': v})

    def load_networkx_graph(self) -> nx.DiGraph:
        """
        Loads the entire Kuzu graph into a NetworkX DiGraph for analysis.
        """
        G = nx.DiGraph()
        
        # Load nodes
        nodes_res = self.conn.execute("MATCH (n:CodeNode) RETURN n.*")
        while nodes_res.has_next():
            row = nodes_res.get_next()
            # row format depends on table order
            # id STRING, file STRING, type STRING, name STRING, start_line INT64, end_line INT64, parent_class STRING, exported BOOLEAN, snippet STRING
            node_id = row[0]
            G.add_node(node_id, **{
                "file": row[1],
                "type": row[2],
                "name": row[3],
                "start_line": row[4],
                "end_line": row[5],
                "parent_class": row[6],
                "exported": row[7],
                "snippet": row[8]
            })
            
        # Load edges
        edges_res = self.conn.execute("MATCH (a:CodeNode)-[r:CallEdge]->(b:CodeNode) RETURN a.id, b.id")
        while edges_res.has_next():
            row = edges_res.get_next()
            G.add_edge(row[0], row[1])
            
        return G
