import io
import zipfile
from pathlib import Path


def make_project_zip(session: dict) -> bytes:
    """Zip generated project files for download."""
    buf = io.BytesIO()
    written: set[str] = set()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in session.get("generated_files", {}).items():
            zf.writestr(path, content)
            written.add(path.replace("\\", "/"))

        if session.get("plan") and "PLAN.md" not in written:
            zf.writestr("PLAN.md", session["plan"])
            written.add("PLAN.md")

        if session.get("architecture") and "ARCHITECTURE.md" not in written:
            zf.writestr("ARCHITECTURE.md", session["architecture"])
            written.add("ARCHITECTURE.md")

        output_root = session.get("output_root")
        if output_root:
            root = Path(output_root)
            if root.is_dir():
                for file_path in root.rglob("*"):
                    if not file_path.is_file():
                        continue
                    rel = file_path.relative_to(root).as_posix()
                    if rel not in written:
                        zf.write(file_path, rel)
                        written.add(rel)

    buf.seek(0)
    return buf.getvalue()
