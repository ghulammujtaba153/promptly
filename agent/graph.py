from langgraph.graph import END, START, StateGraph

from agent.nodes import build_file, create_architecture, create_plan, route_after_build
from agent.prompt_nodes import improve_user_prompt
from agent.state import AppBuilderState
from agent.ui_nodes import (
    create_design_tokens,
    polish_ui,
    review_ui,
    route_after_polish,
    route_after_review,
)


def build_app_graph():
    graph = StateGraph(AppBuilderState)

    graph.add_node("improve_prompt", improve_user_prompt)
    graph.add_node("plan", create_plan)
    graph.add_node("design_tokens", create_design_tokens)
    graph.add_node("architecture", create_architecture)
    graph.add_node("build_file", build_file)
    graph.add_node("review_ui", review_ui)
    graph.add_node("polish_ui", polish_ui)

    graph.add_edge(START, "improve_prompt")
    graph.add_edge("improve_prompt", "plan")
    graph.add_edge("plan", "design_tokens")
    graph.add_edge("design_tokens", "architecture")
    graph.add_edge("architecture", "build_file")
    graph.add_conditional_edges(
        "build_file",
        route_after_build,
        {"build_file": "build_file", "done": "review_ui"},
    )
    graph.add_conditional_edges(
        "review_ui",
        route_after_review,
        {"polish_ui": "polish_ui", "done": END},
    )
    graph.add_conditional_edges(
        "polish_ui",
        route_after_polish,
        {"review_ui": "review_ui"},
    )

    return graph.compile()
