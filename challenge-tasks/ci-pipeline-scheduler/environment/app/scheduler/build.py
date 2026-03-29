from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class Build:
    """Represents a CI build with its state and metadata."""

    build_id: str
    priority: str
    dependencies: List[str] = field(default_factory=list)
    timeout_ms: int = 5000
    resources: Dict[str, int] = field(default_factory=dict)
    preemptible: bool = True
    submit_ts: int = 0
    start_ts: Optional[int] = None
    retry_count: int = 0
    preemption_count: int = 0
    state: str = "pending"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "priority": self.priority,
            "dependencies": self.dependencies,
            "timeout_ms": self.timeout_ms,
            "resources": self.resources,
            "preemptible": self.preemptible,
            "submit_ts": self.submit_ts,
            "start_ts": self.start_ts,
            "retry_count": self.retry_count,
            "preemption_count": self.preemption_count,
        }

    @classmethod
    def from_event(cls, event: Dict[str, Any], default_timeout: int) -> "Build":
        return cls(
            build_id=event["build_id"],
            priority=event["priority"],
            dependencies=event.get("dependencies", []),
            timeout_ms=event.get("timeout_ms", default_timeout),
            resources=event.get("resources", {}),
            preemptible=event.get("preemptible", True),
            submit_ts=event["ts"],
        )
