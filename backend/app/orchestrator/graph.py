import os

from langgraph.graph import StateGraph, START, END

# Ensure LangSmith env vars are applied before graph is compiled.
import app.config  # noqa: F401

from app.orchestrator.state import ReviewState

from app.orchestrator.nodes import (
    build_context,
    run_security,
    run_quality,
    run_tests,
    run_docs,
    aggregate_findings,
    validate_review,
    validate_tests,
    final_decision,
)


def build_review_graph():

    graph = StateGraph(ReviewState)

    # --------------------------------------------------------
    # Nodes
    # --------------------------------------------------------

    graph.add_node(
        "build_context",
        build_context,
    )

    graph.add_node(
        "security",
        run_security,
    )

    graph.add_node(
        "quality",
        run_quality,
    )

    graph.add_node(
        "tests",
        run_tests,
    )

    graph.add_node(
        "docs",
        run_docs,
    )

    graph.add_node(
        "aggregate",
        aggregate_findings,
    )

    graph.add_node(
        "validate",
        validate_review,
    )

    graph.add_node(
        "validate_tests",
        validate_tests,
    )

    graph.add_node(
        "decision",
        final_decision,
    )

    # --------------------------------------------------------
    # START
    # --------------------------------------------------------

    graph.add_edge(
        START,
        "build_context",
    )

    # --------------------------------------------------------
    # Parallel specialist agents
    # --------------------------------------------------------

    graph.add_edge(
        "build_context",
        "security",
    )

    graph.add_edge(
        "build_context",
        "quality",
    )

    graph.add_edge(
        "build_context",
        "tests",
    )

    graph.add_edge(
        "build_context",
        "docs",
    )

    # --------------------------------------------------------
    # Specialist agents -> aggregator
    # --------------------------------------------------------

    graph.add_edge(
        "security",
        "aggregate",
    )

    graph.add_edge(
        "quality",
        "aggregate",
    )

    graph.add_edge(
        "tests",
        "aggregate",
    )

    graph.add_edge(
        "docs",
        "aggregate",
    )

    # --------------------------------------------------------
    # Validation pipeline
    # --------------------------------------------------------

    graph.add_edge(
        "aggregate",
        "validate",
    )

    graph.add_edge(
        "validate",
        "validate_tests",
    )

    graph.add_edge(
        "validate_tests",
        "decision",
    )

    # --------------------------------------------------------
    # END
    # --------------------------------------------------------

    graph.add_edge(
        "decision",
        END,
    )

    compiled = graph.compile()

    # LangGraph sends traces to LangSmith automatically when
    # LANGCHAIN_TRACING_V2=true and LANGCHAIN_API_KEY are set.
    # No extra configuration is needed here — the env vars set by
    # app.config are sufficient.

    return compiled