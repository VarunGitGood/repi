import tree_sitter_python as tspython
import tree_sitter_typescript as tstypescript
import tree_sitter_javascript as tsjavascript
from tree_sitter import Language, Parser, Query, QueryCursor
from .types import CodeNode, CallSite, FileAnalysis
from utils.ids import generate_id
from .queries import (
    PYTHON_ENTITY_QUERY, PYTHON_CALL_QUERY,
    TS_ENTITY_QUERY, TS_CALL_QUERY, JS_ENTITY_QUERY
)

class CodebaseAnalyzer:
    def __init__(self):
        self.languages = {
            'python': Language(tspython.language()),
            'typescript': Language(tstypescript.language_typescript()),
            'tsx': Language(tstypescript.language_tsx()),
            'javascript': Language(tsjavascript.language()),
        }
        self.parsers = {
            name: Parser(lang) for name, lang in self.languages.items()
        }
        
        self.entity_queries = {
            'python': Query(self.languages['python'], PYTHON_ENTITY_QUERY),
            'typescript': Query(self.languages['typescript'], TS_ENTITY_QUERY),
            'tsx': Query(self.languages['tsx'], TS_ENTITY_QUERY),
            'javascript': Query(self.languages['javascript'], JS_ENTITY_QUERY)
        }
                
        self.call_queries = {
            'python': Query(self.languages['python'], PYTHON_CALL_QUERY),
            'typescript': Query(self.languages['typescript'], TS_CALL_QUERY),
            'tsx': Query(self.languages['tsx'], TS_CALL_QUERY),
            'javascript': Query(self.languages['javascript'], TS_CALL_QUERY)
        }

    def _get_parent_class(self, node, lang_name: str) -> str | None:
        curr = node
        class_types = ('class_definition', 'class_declaration', 'class')
        while curr:
            if curr.type in class_types:
                for i in range(curr.child_count):
                    if curr.field_name_for_child(i) == 'name':
                        return curr.child(i).text.decode('utf-8')
            curr = curr.parent
        return None

    def _is_exported(self, node, lang_name: str) -> bool:
        if lang_name == 'python':
            return not node.text.decode('utf-8').startswith('_')
        curr = node
        while curr:
            if curr.type in ('export_statement', 'export_clause', 'export_declaration'):
                return True
            curr = curr.parent
        return False
        
    def _get_snippet(self, node, source_lines: list[str]) -> str:
        start_row = node.start_point[0]
        end_row = min(start_row + 8, node.end_point[0] + 1)
        if start_row < len(source_lines):
            return "\n".join(source_lines[start_row:end_row])
        return ""
        
    def _get_caller_context(self, node) -> str | None:
        curr = node
        func_types = ('function_definition', 'function_declaration', 'method_definition')
        while curr:
            if curr.type in func_types:
                for i in range(curr.child_count):
                    if curr.field_name_for_child(i) == 'name':
                        return curr.child(i).text.decode('utf-8')
            elif curr.type == 'variable_declarator':
                for i in range(curr.child_count):
                    if curr.field_name_for_child(i) == 'name':
                        return curr.child(i).text.decode('utf-8')
            curr = curr.parent
        return None

    def analyze_file(self, file_path: str, source: str) -> FileAnalysis:
        ext = file_path.split('.')[-1].lower()
        if ext == 'py':
            lang_name = 'python'
        elif ext in ('ts', 'tsx'):
            lang_name = ext if ext in self.languages else 'typescript'
        elif ext in ('js', 'jsx', 'mjs', 'cjs'):
            lang_name = 'javascript'
        else:
            return FileAnalysis(file_path, "unknown", [], [], [])
        
        parser = self.parsers[lang_name]
        lang = self.languages[lang_name]
        tree = parser.parse(source.encode('utf-8'))
        source_lines = source.split('\n')
        
        nodes = []
        call_sites = []
        parse_errors = []
        
        if tree.root_node.has_error:
            parse_errors.append("File contains syntax errors")
            
        entity_query = self.entity_queries[lang_name]
        cursor = QueryCursor(entity_query)
        
        # New 0.25 API: Use matches() to get grouped captures
        # returns list of (pattern_index, capture_dict) where capture_dict is {tag: [nodes]}
        try:
            matches = cursor.matches(tree.root_node)
        except Exception as e:
            parse_errors.append(f"Entity query error: {str(e)}")
            matches = []

        # Supported entity types from queries.py
        entity_types = ['function', 'class', 'method', 'interface', 'type_alias', 'enum', 'import']

        for _, capture_dict in matches:
            # Each match should have a .decl and a .name if the query is structured correctly
            for etype in entity_types:
                decl_tag = f"{etype}.decl"
                name_tag = f"{etype}.name"
                
                if decl_tag in capture_dict and name_tag in capture_dict:
                    decl_node = capture_dict[decl_tag][0]
                    name_node = capture_dict[name_tag][0]
                    
                    name_str = name_node.text.decode('utf-8')
                    if etype == 'import':
                        name_str = name_str.strip("'\"")

                    node_type = etype
                    if etype == 'method' and name_str in ('constructor', '__init__'):
                        node_type = 'constructor'
                        
                    start_line = decl_node.start_point[0] + 1
                    end_line = decl_node.end_point[0] + 1
                    
                    parent_class = self._get_parent_class(decl_node, lang_name)
                    exported = self._is_exported(decl_node, lang_name)
                    snippet = self._get_snippet(decl_node, source_lines)
                    
                    node_id = generate_id(file_path, node_type, name_str, start_line)
                    
                    nodes.append(CodeNode(
                        id=node_id,
                        file=file_path,
                        type=node_type,
                        name=name_str,
                        start_line=start_line,
                        end_line=end_line,
                        parent_class=parent_class,
                        exported=exported,
                        snippet=snippet
                    ))
                    break # One etype per match

        call_query = self.call_queries[lang_name]
        try:
            call_cursor = QueryCursor(call_query)
            call_matches = call_cursor.matches(tree.root_node)
            
            for _, capture_dict in call_matches:
                if 'call.node' in capture_dict and 'call.callee' in capture_dict:
                    call_node = capture_dict['call.node'][0]
                    callee_node = capture_dict['call.callee'][0]
                    
                    callee_name = callee_node.text.decode('utf-8')
                    caller_line = call_node.start_point[0] + 1
                    caller_context = self._get_caller_context(call_node)
                    
                    call_sites.append(CallSite(
                        caller_file=file_path,
                        caller_line=caller_line,
                        callee_name=callee_name,
                        caller_context=caller_context
                    ))
        except Exception as e:
            parse_errors.append(f"Call query error: {str(e)}")

        return FileAnalysis(
            file=file_path,
            language=lang_name,
            nodes=nodes,
            call_sites=call_sites,
            parse_errors=parse_errors
        )
