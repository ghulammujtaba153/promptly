import re
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from agent.nodes import _strip_code_fences, _write_text, get_model
from agent.prompts import DESIGN_TOKENS_SYSTEM, UI_POLISH_SYSTEM, UI_REVIEW_SYSTEM
from agent.state import AppBuilderState

MAX_UI_FIX_ROUNDS = 2
UI_PASS_SCORE = 7


def _style_hint(state: AppBuilderState) -> str:
    style = state.get("ui_style", "")
    return f"\nVisual style: {style}\n" if style else ""


def _tokens_hint(state: AppBuilderState) -> str:
    tokens = state.get("design_tokens", "")
    return f"\nDesign tokens (css/tokens.css):\n{tokens}\n" if tokens else ""


def _parse_ui_review(text: str) -> tuple[int, bool, str, str]:
    score_match = re.search(r"SCORE:\s*(\d+)", text, re.IGNORECASE)
    passed_match = re.search(r"PASSED:\s*(yes|no|true|false)", text, re.IGNORECASE)
    summary_match = re.search(r"SUMMARY:\s*(.+?)(?=FIXES:|$)", text, re.IGNORECASE | re.DOTALL)
    fixes_match = re.search(r"FIXES:\s*(.+)$", text, re.IGNORECASE | re.DOTALL)

    score = int(score_match.group(1)) if score_match else UI_PASS_SCORE
    score = max(1, min(10, score))

    if passed_match:
        passed = passed_match.group(1).lower() in {"yes", "true"}
    else:
        passed = score >= UI_PASS_SCORE

    summary = summary_match.group(1).strip() if summary_match else "UI review completed."
    fixes = fixes_match.group(1).strip() if fixes_match else ""
    if fixes.lower() in {"none", "n/a", ""}:
        fixes = ""

    passed = passed or score >= UI_PASS_SCORE
    return score, passed, summary, fixes


def create_design_tokens(state: AppBuilderState) -> dict:
    model = get_model()
    response = model.invoke(
        [
            SystemMessage(content=DESIGN_TOKENS_SYSTEM),
            HumanMessage(
                content=(
                    f"User request:\n{state['user_request']}\n"
                    f"{_style_hint(state)}"
                    f"Plan:\n{state['plan']}\n\n"
                    "Generate css/tokens.css content."
                )
            ),
        ]
    )
    tokens_css = _strip_code_fences(str(response.content))
    return {"design_tokens": tokens_css, "status": "tokens_ready"}


def review_ui(state: AppBuilderState) -> dict:
    files = state.get("generated_files", {})
    html_snippets = "\n\n".join(
        f"--- {path} ---\n{content[:2000]}" for path, content in files.items() if path.endswith(".html")
    )
    css_snippets = "\n\n".join(
        f"--- {path} ---\n{content[:2500]}" for path, content in files.items() if path.endswith(".css")
    )

    score, passed, summary, fix_instructions = UI_PASS_SCORE, True, "UI review skipped.", ""

    try:
        model = get_model()
        response = model.invoke(
            [
                SystemMessage(content=UI_REVIEW_SYSTEM),
                HumanMessage(
                    content=(
                        f"User request:\n{state['user_request']}\n"
                        f"{_style_hint(state)}"
                        f"{_tokens_hint(state)}"
                        f"\nHTML:\n{html_snippets or 'N/A'}\n\nCSS:\n{css_snippets or 'N/A'}\n\n"
                        "Review the UI quality. Keep FIXES brief."
                    )
                ),
            ]
        )
        score, passed, summary, fix_instructions = _parse_ui_review(str(response.content))
    except Exception:
        passed = True
        summary = "UI review unavailable — continuing with generated files."

    review_doc = (
        f"## UI Review (round {state.get('ui_fix_rounds', 0) + 1})\n\n"
        f"**Score:** {score}/10 — {'PASSED' if passed else 'NEEDS POLISH'}\n\n"
        f"{summary}\n\n"
        f"**Fixes:** {fix_instructions if not passed else 'None'}"
    )

    output_root = state.get("output_root")
    if output_root:
        _write_text(Path(output_root) / "UI_REVIEW.md", review_doc)

    return {
        "ui_score": score,
        "ui_passed": passed,
        "ui_review": review_doc,
        "ui_fix_instructions": fix_instructions if not passed else "",
        "status": "ui_reviewed" if passed else "ui_needs_polish",
    }


def polish_ui(state: AppBuilderState) -> dict:
    files = dict(state.get("generated_files", {}))
    css_paths = sorted(p for p in files if p.endswith(".css"))
    if not css_paths:
        return {
            "ui_fix_rounds": state.get("ui_fix_rounds", 0) + 1,
            "ui_passed": True,
            "status": "ui_polish_skipped",
        }

    fix_instructions = state.get("ui_fix_instructions", "")[:2000]
    model = get_model()
    updated = dict(files)

    for path in css_paths:
        try:
            response = model.invoke(
                [
                    SystemMessage(content=UI_POLISH_SYSTEM),
                    HumanMessage(
                        content=(
                            f"User request:\n{state['user_request']}\n"
                            f"{_style_hint(state)}"
                            f"{_tokens_hint(state)}"
                            f"\nReview feedback:\n{fix_instructions}\n\n"
                            f"Polish this file: {path}\n\n"
                            f"Current content:\n```\n{files[path][:8000]}\n```\n\n"
                            "Return the full improved CSS file."
                        )
                    ),
                ]
            )
            content = _strip_code_fences(str(response.content))
            updated[path] = content
            output_root = state.get("output_root")
            if output_root:
                _write_text(Path(output_root) / path, content)
        except Exception:
            continue

    return {
        "generated_files": updated,
        "ui_fix_rounds": state.get("ui_fix_rounds", 0) + 1,
        "ui_passed": False,
        "status": "ui_polished",
    }


def route_after_review(state: AppBuilderState) -> str:
    if state.get("ui_passed"):
        return "done"
    if state.get("ui_fix_rounds", 0) >= MAX_UI_FIX_ROUNDS:
        return "done"
    return "polish_ui"


def route_after_polish(state: AppBuilderState) -> str:
    return "review_ui"
