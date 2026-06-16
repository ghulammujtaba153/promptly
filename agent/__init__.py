def __getattr__(name: str):
    if name == "build_app_graph":
        from agent.graph import build_app_graph

        return build_app_graph
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["build_app_graph"]
