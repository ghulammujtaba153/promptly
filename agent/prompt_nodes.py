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
    model = get_model()
    response = model.invoke(
        [
            SystemMessage(content=PROMPT_IMPROVE_SYSTEM),
            HumanMessage(
                content=(
                    f"{_style_block(state)}"
                    f"Refine this app request into a clear build specification:\n\n{raw}"
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
