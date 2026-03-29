from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class Build:
    """Represents a CI/CD build job with its state and metadata."""

    build_id: str
    priority: str
    dependencies: List[str] = field(default_factory=list)
    timeout_ms: int = 1000
    resources: Dict[str, int] = field(default_factory=dict)
    preemptible: bool = True
    submit_ts: int = 0
    submit_order: int = 0
    start_ts: Optional[int] = None
    start_order: Optional[int] = None
    retry_count: int = 0
    preemption_count: int = 0
    state: str = "pending"

    @classmethod
    def from_event(
        cls,
        event: Dict[str, Any],
        default_timeout: int,
        submit_order: int,
    ) -> "Build":
        return cls(
            build_id=event["build_id"],
            priority=event.get("priority", "normal"),
            dependencies=event.get("dependencies", []),
            timeout_ms=event.get("timeout_ms", default_timeout),
            resources=event.get("resources", {}),
            preemptible=event.get("preemptible", True),
            submit_ts=event["ts"],
            submit_order=submit_order,
        )
