from collections import deque
from datetime import datetime, timedelta
import hashlib
import logging
from typing import Callable

logger = logging.getLogger(__name__)


class TaskObserver:
    def __init__(self, window_size=50, window_duration_minutes=10):
        self.call_buffer = deque(maxlen=window_size)
        self.window_duration = timedelta(minutes=window_duration_minutes)
        self.pattern_threshold = 3
        self.spawn_callbacks: list[Callable] = []

    def record_call(self, tool_name: str, args: dict, result: dict, duration_ms: float = 0):
        call_record = {
            "tool": tool_name,
            "args_hash": self._fingerprint_args(args),
            "timestamp": datetime.now(),
            "result_status": "ok" if not result.get("isError") else "error",
            "duration_ms": duration_ms,
        }
        self.call_buffer.append(call_record)
        patterns = self.detect_repetitive_patterns()
        for pattern in patterns:
            for callback in self.spawn_callbacks:
                try:
                    callback(pattern)
                except Exception as exc:
                    logger.warning("Observer callback error: %s", exc)

    def _fingerprint_args(self, args: dict) -> str:
        normalized = {}
        for k, v in args.items():
            if isinstance(v, str) and ("/" in v or "\\" in v):
                parts = v.replace("\\", "/").split("/")
                normalized[k] = f"FILE:{parts[-1]}" if "." in parts[-1] else "DIR"
            elif isinstance(v, str) and len(v) > 100:
                normalized[k] = f"LONG:{hashlib.md5(v.encode()).hexdigest()[:8]}"
            elif isinstance(v, (list, dict)):
                normalized[k] = hashlib.md5(str(v).encode()).hexdigest()[:8]
            else:
                normalized[k] = v
        return hashlib.md5(str(sorted(normalized.items())).encode()).hexdigest()[:12]

    def detect_repetitive_patterns(self) -> list[dict]:
        now = datetime.now()
        recent = [c for c in self.call_buffer if now - c["timestamp"] < self.window_duration]
        groups: dict[tuple, list] = {}
        for call in recent:
            key = (call["tool"], call["args_hash"])
            groups.setdefault(key, []).append(call)
        tool_groups: dict[str, list] = {}
        for (tool, fp_hash), calls in groups.items():
            tool_groups.setdefault(tool, []).extend(calls)

        patterns = []
        for tool, calls in tool_groups.items():
            if len(calls) >= self.pattern_threshold:
                unique_hashes = len(set(c["args_hash"] for c in calls))
                patterns.append({
                    "tool": tool,
                    "count": len(calls),
                    "unique_targets": unique_hashes,
                    "sample_args": calls[0],
                    "time_span_seconds": (
                        calls[-1]["timestamp"] - calls[0]["timestamp"]
                    ).total_seconds(),
                    "suggested_action": "spawn_sub_agents" if len(calls) >= 5 else "batch",
                })
        return patterns


_observer: TaskObserver | None = None


def get_observer() -> TaskObserver:
    global _observer
    if _observer is None:
        _observer = TaskObserver()
    return _observer
