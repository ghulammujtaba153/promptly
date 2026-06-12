import re
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from agent.nodes import FileItem, _strip_code_fences, _write_text, get_model, get_structured_model
from agent.state import AppBuilderState
from agent.prompts import IMPROVEMENT_ANALYSIS_SYSTEM, IMPROVEMENT_FILE_SYSTEM


class ImprovementOutput(BaseModel):
    improvement_summary: str = Field(description="What will be changed and why")
    files: list[FileItem] = Field(description="Existing files to update, in order")


def analyze_improvement(state: AppBuilderState) -> dict:
    existing_files = state.get("generated_files", {})
    file_listing = "\n".join(
        f"- `{path}` ({len(content)} chars)" for path, content in existing_files.items()
    )

    model = get_structured_model(ImprovementOutput)
    result = model.invoke(
        [
            SystemMessage(content=IMPROVEMENT_ANALYSIS_SYSTEM),
            HumanMessage(
                content=(
                    f"Improvement request:\n{state['user_request']}\n\n"
                    f"Original plan:\n{state.get('plan', 'N/A')}\n\n"
                    f"Architecture:\n{state.get('architecture', 'N/A')}\n\n"
                    f"Design tokens:\n{state.get('design_tokens', 'N/A')}\n\n"
                    f"Existing files:\n{file_listing}\n\n"
                    "Return which files to update and how."
                )
            ),
        ]
    )

    file_queue = [{"path": f.path, "purpose": f.purpose} for f in result.files]
    improvement_doc = f"## Improvement\n\n{result.improvement_summary}\n\n### Files to update\n" + "\n".join(
        f"- `{f.path}` — {f.purpose}" for f in result.files
    )

    output_root = state.get("output_root", "")
    if output_root:
        _write_text(Path(output_root) / "IMPROVEMENTS.md", improvement_doc)

    return {
        "architecture": state.get("architecture", "") + "\n\n" + improvement_doc,
        "file_queue": file_queue,
        "current_file_index": 0,
        "status": "improvement_planned",
    }


def improve_file(state: AppBuilderState) -> dict:
    index = state.get("current_file_index", 0)
    file_queue = state["file_queue"]
    file_spec = file_queue[index]
    path = file_spec["path"]
    purpose = file_spec["purpose"]

    existing_files = state.get("generated_files", {})
    current_content = existing_files.get(path, "")

    model = get_model()
    response = model.invoke(
        [
            SystemMessage(content=IMPROVEMENT_FILE_SYSTEM),
            HumanMessage(
                content=(
                    f"Improvement request:\n{state['user_request']}\n\n"
                    f"Plan:\n{state.get('plan', '')}\n\n"
                    f"Design tokens:\n{state.get('design_tokens', '')}\n\n"
                    f"File to update: {path}\n"
                    f"Instructions: {purpose}\n\n"
                    f"Current file content:\n```\n{current_content}\n```\n\n"
                    "Return the full updated file content only."
                )
            ),
        ]
    )

    content = _strip_code_fences(str(response.content))
    output_root = state.get("output_root")
    if output_root:
        _write_text(Path(output_root) / path, content)

    updated_files = {**existing_files, path: content}
    return {
        "generated_files": updated_files,
        "current_file_index": index + 1,
        "status": f"improved:{path}",
    }


def route_after_improve(state: AppBuilderState) -> str:
    if state.get("current_file_index", 0) < len(state.get("file_queue", [])):
        return "improve_file"
    return "done"
