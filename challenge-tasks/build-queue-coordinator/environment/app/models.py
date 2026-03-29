from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class Transition:
    ts: int
    build_id: str
    from_state: Optional[str]
    to_state: str
    note: str


@dataclass
class Summary:
    transitions: List[Transition]
    final_states: Dict[str, str]
    completed: List[str]
    failed: List[str]
    cancelled: List[str]
    pending: List[str]
    running: List[str]
    retry_counts: Dict[str, int]
    preemption_counts: Dict[str, int]
    resource_usage: Dict[str, int]
