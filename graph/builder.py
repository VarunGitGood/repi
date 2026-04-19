import networkx as nx
from extractor.types import FileAnalysis

class GraphBuilder:
    def build(self, analyses: list[FileAnalysis]) -> nx.DiGraph:
        G = nx.DiGraph()
        
        for fa in analyses:
            for node in fa.nodes:
                G.add_node(node.id, **node.__dict__)
                
        name_to_ids = {}
        for fa in analyses:
            for node in fa.nodes:
                if node.name not in name_to_ids:
                    name_to_ids[node.name] = []
                name_to_ids[node.name].append(node.id)
                
        for fa in analyses:
            file_funcs = {n.name: n.id for n in fa.nodes if n.type in ('function', 'method', 'arrow_function', 'function_definition')}
            
            for cs in fa.call_sites:
                caller_id = None
                if cs.caller_context and cs.caller_context in file_funcs:
                    caller_id = file_funcs[cs.caller_context]
                    
                if caller_id and cs.callee_name in name_to_ids:
                    for callee_id in name_to_ids[cs.callee_name]:
                        G.add_edge(caller_id, callee_id, type='calls')
                        
        return G
