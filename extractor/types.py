from dataclasses import dataclass
from typing import Optional


@dataclass
class CodeNode:
    id: str  # deterministic hash of file:type:name:start_line, 12 chars
    file: str  # relative path from repo root
    type: str  # function | arrow_function | class | method | constructor | import | interface | type_alias | enum
    name: str  # identifier text, or module specifier for imports
    start_line: int  # 1-indexed (git diff compatible)
    end_line: int  # 1-indexed
    parent_class: Optional[str]  # for methods, the containing class name
    exported: bool  # whether this entity is publicly exported
    snippet: str  # first 8 lines of the entity block


@dataclass
class CallSite:
    caller_file: str
    caller_line: int
    callee_name: str  # raw identifier (Phase 2 resolves to a node ID)
    caller_context: Optional[str]  # enclosing function/method name


@dataclass
class FileAnalysis:
    file: str
    language: str
    nodes: list[CodeNode]
    call_sites: list[CallSite]
    parse_errors: list[str]
