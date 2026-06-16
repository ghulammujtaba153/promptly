"""Nodes that refine user prompts before planning or improvements."""

from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from agent.nodes import _strip_code_fences, _write_text, get_model
from agent.prompts import PROMPT_IMPROVE_SYSTEM
from agent.state import AppBuilderState


def _style_block(state: AppBuilderState) -> str:
    style = state.get("ui_style", "")
    return f"Visual style direction:\n{style}\n\n" if style else ""


def improve_user_prompt(state: AppBuilderState) -> dict:
    """Expand a vague user prompt into a clear, build-ready specification."""
    raw = state["user_request"].strip()
    chat_history = state.get("chat_history", "").strip()
    plan = state.get("plan", "").strip()
    architecture = state.get("architecture", "").strip()
    generated_files = state.get("generated_files", {}) or {}
    model = get_model()

    context_parts: list[str] = []
    if plan:
        context_parts.append(f"Existing plan:\n{plan}")
    if architecture:
        context_parts.append(f"Existing architecture:\n{architecture}")
    if chat_history:
        context_parts.append(f"Session chat history (most recent last):\n{chat_history}")
    if generated_files:
        file_listing = "\n".join(
            f"- {path} ({len(content)} chars)"
            for path, content in list(generated_files.items())[:12]
        )
        context_parts.append(f"Existing project files:\n{file_listing}")
    context_block = "\n\n".join(context_parts).strip()

    response = model.invoke(
        [
            SystemMessage(content=PROMPT_IMPROVE_SYSTEM),
            HumanMessage(
                content=(
                    f"{_style_block(state)}"
                    "Use the current session context to keep continuity.\n\n"
                    f"{context_block + '\n\n' if context_block else ''}"
                    f"Improvement request:\n{raw}"
                )
            ),
        ]
    )

    improved = _strip_code_fences(str(response.content)).strip() or raw

    output_root = state.get("output_root")
    if output_root:
        project_dir = Path(output_root)
        if project_dir.is_dir() and (
            (project_dir / "index.html").exists() or list(project_dir.glob("*.html"))
        ):
            _write_text(project_dir / "IMPROVED_PROMPT.md", improved)

    print(f"\n=== PROMPT IMPROVED ===\n{improved}\n")

    return {
        "raw_user_request": raw,
        "improved_prompt": improved,
        "user_request": improved,
        "status": "prompt_improved",
    }
