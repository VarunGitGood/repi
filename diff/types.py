from dataclasses import dataclass, field
from extractor.types import CodeNode

@dataclass
class DiffHunk:
    file: str  # Relative path matches Kuzu
    start_line: int # 1-indexed, + side
    end_line: int
    change_type: str # "modified" | "added" | "deleted"

@dataclass
class SeedNode(CodeNode):
    changed_lines: list[int] = field(default_factory=list)
    change_type: str = "modified"

@dataclass
class ImpactedNode(CodeNode):
    distance: int = 0
    risk_score: float = 0.0
    pagerank: float = 0.0
    betweenness: float = 0.0
    churn: float = 0.0
    path_from_seed: list[str] = field(default_factory=list)

@dataclass
class ImpactResult:
    ref: str
    seed_nodes: list[SeedNode] = field(default_factory=list)
    blast_radius: list[ImpactedNode] = field(default_factory=list)
    total_nodes_affected: int = 0
    max_distance: int = 0
    analysis_duration_ms: int = 0
