import re
from pathlib import Path

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from agent.config import MODEL_ID, MODEL_TEMPERATURE
from agent.state import AppBuilderState
from agent.prompts import (
    ARCHITECTURE_SYSTEM,
    FILE_BUILD_CSS_SYSTEM,
    FILE_BUILD_HTML_SYSTEM,
    FILE_BUILD_JS_SYSTEM,
    PLAN_SYSTEM,
)

_model = None


def get_model():
    global _model
    if _model is None:
        _model = init_chat_model(MODEL_ID, temperature=MODEL_TEMPERATURE)
    return _model


def get_structured_model(schema: type[BaseModel]):
    """Structured output tuned for gpt-oss-120b on Groq."""
    return get_model().with_structured_output(schema, method="json_schema")


class FileItem(BaseModel):
    path: str = Field(description="Relative file path, e.g. css/styles.css")
    purpose: str = Field(description="What this file does")


class ArchitectureOutput(BaseModel):
    project_name: str = Field(description="Short slug for the project folder, e.g. todo-app")
    summary: str = Field(description="One paragraph architecture overview")
    files: list[FileItem] = Field(description="Files to create, in build order")


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    match = re.match(r"^```[\w]*\n(.*)\n```$", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _style_block(state: AppBuilderState) -> str:
    style = state.get("ui_style", "")
    return f"Visual style direction:\n{style}\n\n" if style else ""


def _file_build_system(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".html"):
        return FILE_BUILD_HTML_SYSTEM
    if lower.endswith(".css"):
        return FILE_BUILD_CSS_SYSTEM
    if lower.endswith(".js"):
        return FILE_BUILD_JS_SYSTEM
    return FILE_BUILD_CSS_SYSTEM


def create_plan(state: AppBuilderState) -> dict:
    model = get_model()
    response = model.invoke(
        [
            SystemMessage(content=PLAN_SYSTEM),
            HumanMessage(
                content=f"{_style_block(state)}Build this application:\n\n{state['user_request']}"
            ),
        ]
    )
    plan = response.content
    print("\n=== PLAN ===\n")
    print(plan)
    return {"plan": plan, "status": "planned"}


def create_architecture(state: AppBuilderState) -> dict:
    model = get_structured_model(ArchitectureOutput)
    result = model.invoke(
        [
            SystemMessage(content=ARCHITECTURE_SYSTEM),
            HumanMessage(
                content=(
                    f"User request:\n{state['user_request']}\n\n"
                    f"{_style_block(state)}"
                    f"Approved plan:\n{state['plan']}\n\n"
                    f"Design tokens already defined for css/tokens.css:\n"
                    f"{state.get('design_tokens', 'N/A')}\n\n"
                    "Return the file structure and build order. "
                    "Must include css/tokens.css before css/styles.css."
                )
            ),
        ]
    )

    project_name = re.sub(r"[^\w\-]", "-", result.project_name.lower()).strip("-")
    output_root = str(Path(state.get("output_root", "output")) / project_name)
    project_dir = Path(output_root)
    project_dir.mkdir(parents=True, exist_ok=True)

    architecture_doc = (
        f"# Architecture: {project_name}\n\n"
        f"{result.summary}\n\n"
        "## Files\n\n"
        + "\n".join(f"- `{f.path}` — {f.purpose}" for f in result.files)
    )
    _write_text(project_dir / "ARCHITECTURE.md", architecture_doc)
    _write_text(project_dir / "PLAN.md", state["plan"])
    if state.get("improved_prompt"):
        _write_text(project_dir / "IMPROVED_PROMPT.md", state["improved_prompt"])

    print("\n=== ARCHITECTURE ===\n")
    print(architecture_doc)
    print(f"\nProject directory: {output_root}")

    file_queue = [{"path": f.path, "purpose": f.purpose} for f in result.files]

    return {
        "project_name": project_name,
        "output_root": output_root,
        "architecture": architecture_doc,
        "file_queue": file_queue,
        "current_file_index": 0,
        "generated_files": {},
        "status": "architected",
    }


def build_file(state: AppBuilderState) -> dict:
    index = state.get("current_file_index", 0)
    file_queue = state["file_queue"]
    file_spec = file_queue[index]
    path = file_spec["path"]
    purpose = file_spec["purpose"]

    existing = state.get("generated_files", {})
    existing_summary = (
        "\n".join(f"- {p} (already created)" for p in existing) if existing else "None yet"
    )

    tokens = state.get("design_tokens", "")
    if path.endswith("tokens.css") and tokens:
        content = tokens
        file_path = Path(state["output_root"]) / path
        _write_text(file_path, content)
        updated_files = {**existing, path: content}
        print(f"\n=== BUILT ({index + 1}/{len(file_queue)}) === {path} (design tokens)")
        return {
            "generated_files": updated_files,
            "current_file_index": index + 1,
            "status": f"built:{path}",
        }

    model = get_model()
    response = model.invoke(
        [
            SystemMessage(content=_file_build_system(path)),
            HumanMessage(
                content=(
                    f"User request:\n{state['user_request']}\n\n"
                    f"{_style_block(state)}"
                    f"Plan:\n{state['plan']}\n\n"
                    f"Architecture:\n{state['architecture']}\n\n"
                    f"Design tokens (css/tokens.css):\n{tokens or 'N/A'}\n\n"
                    f"Files already created:\n{existing_summary}\n\n"
                    f"Now create this file:\n"
                    f"Path: {path}\n"
                    f"Purpose: {purpose}\n\n"
                    "Return only the file content."
                )
            ),
        ]
    )

    content = _strip_code_fences(str(response.content))
    file_path = Path(state["output_root"]) / path
    _write_text(file_path, content)

    print(f"\n=== BUILT ({index + 1}/{len(file_queue)}) === {path}")

    updated_files = {**existing, path: content}
    return {
        "generated_files": updated_files,
        "current_file_index": index + 1,
        "status": f"built:{path}",
    }


def route_after_build(state: AppBuilderState) -> str:
    if state.get("current_file_index", 0) < len(state.get("file_queue", [])):
        return "build_file"
    return "done"
