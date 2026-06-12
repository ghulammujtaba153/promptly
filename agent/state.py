from typing import TypedDict


class FileSpec(TypedDict):
    path: str
    purpose: str


class AppBuilderState(TypedDict, total=False):
    user_request: str
    ui_style: str
    output_root: str
    project_name: str
    plan: str
    design_tokens: str
    architecture: str
    file_queue: list[FileSpec]
    current_file_index: int
    generated_files: dict[str, str]
    ui_score: int
    ui_passed: bool
    ui_review: str
    ui_fix_instructions: str
    ui_fix_rounds: int
    status: str
    error: str
