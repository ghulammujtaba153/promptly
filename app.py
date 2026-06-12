import hashlib
import uuid
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from agent.config import MODEL_ID, UI_STYLE_PRESETS
from agent.graph import build_app_graph
from agent.improve_graph import build_improve_graph
from agent.preview import build_preview_bundle, build_preview_html
from agent.utils import make_project_zip
from agent.voice import transcribe_audio

load_dotenv()

OUTPUT_ROOT = Path("output")

st.set_page_config(
    page_title="Promptly",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    [data-testid="stSidebar"] { display: none; }
    .block-container { padding-top: 1rem; padding-bottom: 0; max-width: 100%; }
    .lovable-header {
        font-size: 1.35rem; font-weight: 700;
        background: linear-gradient(120deg, #818cf8, #c084fc);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    }
    .panel {
        border: 1px solid #1e293b; border-radius: 12px;
        background: #0b1120; padding: 0.75rem 1rem; height: calc(100vh - 7rem);
        overflow-y: auto;
    }
    .chat-panel { display: flex; flex-direction: column; }
    .status-pill {
        display: inline-block; padding: 0.15rem 0.6rem; border-radius: 999px;
        font-size: 0.75rem; background: #1e293b; color: #94a3b8;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] { border-color: #1e293b !important; }

    /* Keep preview panel fixed while left chat scrolls */
    div[data-testid="stHorizontalBlock"] {
        align-items: flex-start !important;
    }
    div[data-testid="column"]:has(.promptly-preview-marker) {
        position: sticky !important;
        top: 1.25rem !important;
        align-self: flex-start !important;
        z-index: 100 !important;
        margin-top: 0.75rem !important;
    }
    div[data-testid="column"]:has(.promptly-preview-marker) [data-testid="stVerticalBlockBorderWrapper"] {
        min-height: 580px;
    }
    div[data-testid="column"]:has(.promptly-preview-marker) [data-testid="stTabContent"] {
        min-height: 500px;
    }
    div[data-testid="column"]:has(.promptly-preview-marker) iframe {
        width: 100% !important;
        min-height: 480px !important;
        display: block !important;
        background: #ffffff;
        border-radius: 8px;
    }
    .promptly-preview-empty {
        min-height: 480px;
        display: flex;
        align-items: center;
        justify-content: center;
        color: #94a3b8;
        font-family: sans-serif;
        border: 1px dashed #334155;
        border-radius: 8px;
        background: #0f172a;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

BUILD_STEPS = ["plan", "design_tokens", "architecture", "build_file", "review_ui", "polish_ui"]


def new_session(name: str = "New project") -> dict:
    return {
        "id": str(uuid.uuid4())[:8],
        "name": name,
        "messages": [],
        "plan": None,
        "architecture": None,
        "generated_files": {},
        "project_name": None,
        "output_root": None,
        "design_tokens": None,
        "ui_review": None,
        "created_at": datetime.now().isoformat(),
        "building": False,
    }


def init_session_state() -> None:
    if "sessions" not in st.session_state:
        st.session_state.sessions = {}
    if "active_session_id" not in st.session_state:
        session = new_session()
        st.session_state.sessions[session["id"]] = session
        st.session_state.active_session_id = session["id"]
    if "selected_file" not in st.session_state:
        st.session_state.selected_file = None
    if "right_tab" not in st.session_state:
        st.session_state.right_tab = "Preview"
    if "last_voice_hash" not in st.session_state:
        st.session_state.last_voice_hash = None
    if "preview_page" not in st.session_state:
        st.session_state.preview_page = "index.html"
    if "prompt_draft" not in st.session_state:
        st.session_state.prompt_draft = ""
    if "voice_status" not in st.session_state:
        st.session_state.voice_status = None
    if "voice_input_version" not in st.session_state:
        st.session_state.voice_input_version = 0
    if "pending_voice_text" not in st.session_state:
        st.session_state.pending_voice_text = None
    if "ui_style" not in st.session_state:
        st.session_state.ui_style = list(UI_STYLE_PRESETS.keys())[0]


def active_session() -> dict:
    return st.session_state.sessions[st.session_state.active_session_id]


def set_active(session: dict) -> None:
    st.session_state.sessions[session["id"]] = session


def add_message(session: dict, role: str, content: str) -> None:
    session["messages"].append({"role": role, "content": content, "at": datetime.now().isoformat()})


def load_project_from_disk(project_dir: Path) -> dict:
    session = new_session(name=project_dir.name)
    session["project_name"] = project_dir.name
    session["output_root"] = str(project_dir)

    for path in project_dir.rglob("*"):
        if path.is_file() and path.suffix in {".html", ".css", ".js"}:
            rel = path.relative_to(project_dir).as_posix()
            session["generated_files"][rel] = path.read_text(encoding="utf-8")

    tokens_path = project_dir / "css" / "tokens.css"
    if tokens_path.exists():
        session["design_tokens"] = tokens_path.read_text(encoding="utf-8")

    for doc in ("PLAN.md", "ARCHITECTURE.md", "UI_REVIEW.md"):
        doc_path = project_dir / doc
        if doc_path.exists():
            if doc == "PLAN.md":
                session["plan"] = doc_path.read_text(encoding="utf-8")
            elif doc == "ARCHITECTURE.md":
                session["architecture"] = doc_path.read_text(encoding="utf-8")
            elif doc == "UI_REVIEW.md":
                session["ui_review"] = doc_path.read_text(encoding="utf-8")

    add_message(session, "assistant", f"Loaded project **{project_dir.name}** ({len(session['generated_files'])} files).")
    return session


def run_build(session: dict, user_request: str, placeholders: dict) -> None:
    graph = build_app_graph()
    ui_style = UI_STYLE_PRESETS.get(st.session_state.ui_style, "")
    initial = {
        "user_request": user_request,
        "ui_style": ui_style,
        "output_root": str(OUTPUT_ROOT),
        "current_file_index": 0,
        "generated_files": {},
        "ui_fix_rounds": 0,
        "status": "starting",
    }

    progress = placeholders["progress"]
    status = placeholders["status"]
    step = 0
    total_steps = len(BUILD_STEPS)
    built = 0
    queue_len = 0

    for event in graph.stream(initial, stream_mode="updates"):
        for node, update in event.items():
            if node == "plan":
                session["plan"] = update.get("plan")
                step += 1
                progress.progress(step / total_steps, text="Planning…")
                status.info("📋 Plan created")
                add_message(session, "assistant", "Plan ready. Creating design tokens…")

            elif node == "design_tokens":
                session["design_tokens"] = update.get("design_tokens")
                step += 1
                progress.progress(step / total_steps, text="Design tokens…")
                status.info("🎨 Design tokens ready")
                add_message(session, "assistant", "Design system defined. Architecting files…")

            elif node == "architecture":
                session["architecture"] = update.get("architecture")
                session["project_name"] = update.get("project_name")
                session["output_root"] = update.get("output_root")
                session["name"] = update.get("project_name", session["name"])
                queue_len = len(update.get("file_queue", []))
                step += 1
                progress.progress(step / total_steps, text="Architecture ready")
                status.info(f"🏗 Architecture — {queue_len} files queued")
                add_message(session, "assistant", f"Architecture ready. Building {queue_len} files…")

            elif node == "build_file":
                session["generated_files"] = update.get("generated_files", {})
                built = update.get("current_file_index", built)
                file_name = update.get("status", "").replace("built:", "")
                pct = (step + built / max(queue_len, 1)) / total_steps
                progress.progress(min(pct, 0.85), text=f"Building {built}/{queue_len}")
                status.info(f"📄 {file_name}")
                if file_name:
                    add_message(session, "assistant", f"Created `{file_name}`")

            elif node == "review_ui":
                session["ui_review"] = update.get("ui_review")
                score = update.get("ui_score", "?")
                passed = update.get("ui_passed", False)
                step += 1
                progress.progress(step / total_steps, text="UI review…")
                if passed:
                    status.success(f"✅ UI passed ({score}/10)")
                    add_message(session, "assistant", f"UI review passed — **{score}/10**")
                else:
                    status.warning(f"🔄 Polishing UI ({score}/10)")
                    add_message(session, "assistant", f"UI scored **{score}/10** — polishing styles…")

            elif node == "polish_ui":
                session["generated_files"] = update.get("generated_files", {})
                status.info("✨ Polishing CSS…")
                add_message(session, "assistant", "Applied UI polish pass")

    progress.progress(1.0, text="Done")
    status.success("✅ Build complete")
    add_message(session, "assistant", "Your app is ready. Ask me to improve design, add features, or fix anything.")


def run_improve(session: dict, user_request: str, placeholders: dict) -> None:
    graph = build_improve_graph()
    initial = {
        "user_request": user_request,
        "plan": session.get("plan", ""),
        "architecture": session.get("architecture", ""),
        "generated_files": session.get("generated_files", {}),
        "output_root": session.get("output_root", ""),
        "design_tokens": session.get("design_tokens", ""),
        "ui_style": UI_STYLE_PRESETS.get(st.session_state.ui_style, ""),
        "current_file_index": 0,
        "status": "improving",
    }

    progress = placeholders["progress"]
    status = placeholders["status"]
    improved = 0
    queue_len = 0

    for event in graph.stream(initial, stream_mode="updates"):
        for node, update in event.items():
            if node == "analyze_improvement":
                queue_len = len(update.get("file_queue", []))
                session["architecture"] = update.get("architecture", session.get("architecture"))
                progress.progress(0.2, text="Analyzing improvements…")
                status.info(f"🔍 Updating {queue_len} files")
                add_message(session, "assistant", f"Improvement plan ready — updating {queue_len} file(s)…")

            elif node == "improve_file":
                session["generated_files"] = update.get("generated_files", {})
                improved = update.get("current_file_index", improved)
                file_name = update.get("status", "").replace("improved:", "")
                if queue_len:
                    progress.progress(0.2 + 0.8 * (improved / queue_len), text=f"Updating {improved}/{queue_len}")
                status.info(f"✏️ {file_name}")
                if file_name:
                    add_message(session, "assistant", f"Updated `{file_name}`")

    progress.progress(1.0, text="Done")
    status.success("✅ Improvements applied")
    add_message(session, "assistant", "Changes applied. Check the preview on the right.")


def render_session_bar() -> None:
    cols = st.columns([2, 1, 1, 1])
    with cols[0]:
        st.markdown('<span class="lovable-header">⚡ Promptly</span>', unsafe_allow_html=True)
        st.caption(f"Model: `{MODEL_ID.replace('groq:', '')}`")
    with cols[1]:
        if st.button("＋ New project", use_container_width=True):
            session = new_session()
            st.session_state.sessions[session["id"]] = session
            st.session_state.active_session_id = session["id"]
            st.session_state.selected_file = None
            st.session_state.prompt_draft = ""
            st.session_state.voice_status = None
            st.session_state.last_voice_hash = None
            st.session_state.pending_voice_text = None
            st.session_state.voice_input_version += 1
            st.rerun()
    with cols[2]:
        session_ids = list(st.session_state.sessions.keys())
        labels = [st.session_state.sessions[sid]["name"] for sid in session_ids]
        idx = session_ids.index(st.session_state.active_session_id)
        picked = st.selectbox("Session", labels, index=idx, label_visibility="collapsed")
        if labels[idx] != picked:
            new_id = session_ids[labels.index(picked)]
            st.session_state.active_session_id = new_id
            st.session_state.selected_file = None
            st.rerun()
    with cols[3]:
        if OUTPUT_ROOT.exists():
            projects = sorted(
                [p for p in OUTPUT_ROOT.iterdir() if p.is_dir()],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if projects:
                load_name = st.selectbox("Load", ["—"] + [p.name for p in projects], label_visibility="collapsed", key="load_project_pick")
                if st.button("Open", use_container_width=True, disabled=load_name == "—"):
                    loaded = load_project_from_disk(OUTPUT_ROOT / load_name)
                    st.session_state.sessions[loaded["id"]] = loaded
                    st.session_state.active_session_id = loaded["id"]
                    st.session_state.load_project_pick = "—"
                    st.rerun()


def submit_prompt(session: dict, text: str) -> None:
    if not text.strip() or session.get("building"):
        return
    add_message(session, "user", text.strip())
    session["building"] = True
    set_active(session)
    st.rerun()


def handle_voice_input(session: dict) -> None:
    version = st.session_state.voice_input_version
    audio = st.audio_input(
        "Voice prompt (Whisper)",
        disabled=session.get("building", False),
        key=f"voice_prompt_{version}",
    )
    if audio is None:
        return

    audio_bytes = audio.getvalue()
    if not audio_bytes:
        return

    audio_hash = hashlib.md5(audio_bytes).hexdigest()
    if audio_hash == st.session_state.last_voice_hash:
        return

    st.session_state.last_voice_hash = audio_hash

    with st.spinner("Transcribing with Whisper…"):
        try:
            text = transcribe_audio(audio_bytes, audio.type or "audio/wav")
        except Exception as exc:
            st.session_state.voice_status = None
            st.session_state.pending_voice_text = None
            st.error(f"Voice transcription failed: {exc}")
            return

    if text.strip():
        st.session_state.pending_voice_text = text.strip()
        st.session_state.voice_status = "Transcribed — edit if needed, then press Send"
        st.session_state.voice_input_version += 1
        st.rerun()


def render_chat_panel(session: dict) -> None:
    st.markdown("##### Chat")

    if not session["messages"]:
        st.caption("Describe the app you want to build — type or use the microphone below.")

    for msg in session["messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    is_improvement = bool(session.get("generated_files"))
    placeholder = "Improve design, add a feature, fix a bug…" if is_improvement else "Describe your app…"

    st.selectbox(
        "UI style",
        list(UI_STYLE_PRESETS.keys()),
        key="ui_style",
        label_visibility="collapsed",
        disabled=session.get("building", False),
    )

    if st.session_state.pending_voice_text:
        st.session_state.prompt_draft = st.session_state.pending_voice_text
        st.session_state.pending_voice_text = None

    if st.session_state.voice_status:
        st.caption(st.session_state.voice_status)

    st.text_area(
        "Prompt",
        placeholder=placeholder,
        height=88,
        disabled=session.get("building", False),
        label_visibility="collapsed",
        key="prompt_draft",
    )

    handle_voice_input(session)

    if st.button(
        "Send",
        type="primary",
        disabled=session.get("building", False) or not st.session_state.prompt_draft.strip(),
        use_container_width=True,
    ):
        submit_prompt(session, st.session_state.prompt_draft.strip())
        st.session_state.prompt_draft = ""
        st.session_state.voice_status = None
        st.session_state.last_voice_hash = None
        st.session_state.pending_voice_text = None
        st.session_state.voice_input_version += 1
        st.rerun()

    if session.get("building") and session["messages"] and session["messages"][-1]["role"] == "user":
        user_request = session["messages"][-1]["content"]
        progress = st.progress(0, text="Working…")
        status = st.empty()
        placeholders = {"progress": progress, "status": status}

        try:
            if session.get("generated_files"):
                run_improve(session, user_request, placeholders)
            else:
                run_build(session, user_request, placeholders)
        except Exception as exc:
            add_message(session, "assistant", f"❌ Error: {exc}")
            status.error(str(exc))
        finally:
            session["building"] = False
            set_active(session)
            st.rerun()


def render_preview_panel(session: dict) -> None:
    tab_preview, tab_code, tab_plan = st.tabs(["Preview", "Code", "Plan"])

    files = session.get("generated_files", {})

    with tab_preview:
        if files:
            html_pages = sorted(p for p in files if p.lower().endswith(".html"))
            preview_cols = st.columns([2, 1])
            with preview_cols[0]:
                default_page = html_pages[0] if html_pages else "index.html"
                if st.session_state.get("preview_page") not in html_pages:
                    st.session_state.preview_page = default_page
                st.selectbox(
                    "Page",
                    html_pages,
                    key="preview_page",
                    label_visibility="collapsed",
                )
            with preview_cols[1]:
                st.caption("Links stay inside preview")

            bundle = build_preview_bundle(files)
            page = st.session_state.preview_page
            if page not in bundle:
                page = next(iter(bundle))
            preview_html = bundle.get(page) or build_preview_html(files, start_page=page)
            if preview_html:
                st.components.v1.html(
                    preview_html,
                    height=500,
                    scrolling=True,
                )
            else:
                st.warning("Could not render preview for this page.")
        else:
            st.markdown(
                '<div class="promptly-preview-empty">'
                "Preview will appear here after your first build"
                "</div>",
                unsafe_allow_html=True,
            )

    with tab_code:
        if not files:
            st.caption("No files yet.")
        else:
            file_paths = sorted(files.keys())
            default_idx = 0
            if st.session_state.selected_file in file_paths:
                default_idx = file_paths.index(st.session_state.selected_file)

            selected = st.selectbox("File", file_paths, index=default_idx, label_visibility="collapsed")
            st.session_state.selected_file = selected
            lang = {".html": "html", ".css": "css", ".js": "javascript"}.get(
                Path(selected).suffix.lower(), "text"
            )
            st.code(files[selected], language=lang, line_numbers=True)

    with tab_plan:
        if session.get("plan"):
            st.markdown("#### Plan")
            st.markdown(session["plan"])
        if session.get("architecture"):
            st.markdown("#### Architecture")
            st.markdown(session["architecture"])
        if session.get("design_tokens"):
            st.markdown("#### Design tokens")
            st.code(session["design_tokens"], language="css")
        if session.get("ui_review"):
            st.markdown("#### UI review")
            st.markdown(session["ui_review"])
        if not session.get("plan") and not session.get("architecture"):
            st.caption("Plan and architecture appear after the first build.")


def main() -> None:
    init_session_state()
    render_session_bar()

    left, right = st.columns([2, 3], gap="medium")

    session = active_session()

    with left:
        with st.container(border=True):
            render_chat_panel(session)

    with right:
        st.markdown('<span class="promptly-preview-marker"></span>', unsafe_allow_html=True)
        with st.container(border=True):
            header_l, header_r = st.columns([3, 1])
            with header_l:
                if session.get("project_name"):
                    st.caption(f"`{session['project_name']}` · {len(session.get('generated_files', {}))} files")
            with header_r:
                files = session.get("generated_files", {})
                if files or session.get("output_root"):
                    zip_name = f"{session.get('project_name') or 'promptly-project'}.zip"
                    st.download_button(
                        "⬇ Download",
                        data=make_project_zip(session),
                        file_name=zip_name,
                        mime="application/zip",
                        use_container_width=True,
                    )
            render_preview_panel(session)


if __name__ == "__main__":
    main()
