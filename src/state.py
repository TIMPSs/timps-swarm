"""
Shared state schema for the TIMPS Swarm multi-agent system.
All agents read/write to this shared state via LangGraph.
"""
from typing import Annotated, List, Optional, Dict, Any
from typing_extensions import TypedDict
import operator


class Task(TypedDict):
    id: str
    description: str
    assigned_to: str        # agent name
    status: str             # pending | running | completed | failed
    dependencies: List[str]
    output: Optional[str]
    artifact_path: Optional[str]
    created_at: Optional[str]
    completed_at: Optional[str]
    retry_count: int


class SwarmState(TypedDict):
    # Input
    user_request: str
    language: Optional[str]

    # Planning outputs
    requirements: str
    architecture_plan: str

    # Task management
    tasks: Annotated[List[Task], operator.add]

    # Code artifacts
    code_artifacts: Annotated[List[str], operator.add]

    # Review outputs
    review_comments: Annotated[List[str], operator.add]
    test_results: str
    security_report: str

    # Performance
    performance_report: str

    # Final output
    documentation: str
    final_deliverable: str

    # Control
    iteration_count: int
    max_iterations: int
    errors: Annotated[List[str], operator.add]
    completed: bool
