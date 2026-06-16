from langgraph.graph import END, START, StateGraph

from agent.improve_nodes import analyze_improvement, improve_file, route_after_improve
from agent.prompt_nodes import improve_user_prompt
from agent.state import AppBuilderState


def build_improve_graph():
    graph = StateGraph(AppBuilderState)

    graph.add_node("improve_prompt", improve_user_prompt)
    graph.add_node("analyze_improvement", analyze_improvement)
    graph.add_node("improve_file", improve_file)

    graph.add_edge(START, "improve_prompt")
    graph.add_edge("improve_prompt", "analyze_improvement")
    graph.add_edge("analyze_improvement", "improve_file")
    graph.add_conditional_edges(
        "improve_file",
        route_after_improve,
        {
            "improve_file": "improve_file",
            "done": END,
        },
    )

    return graph.compile()
