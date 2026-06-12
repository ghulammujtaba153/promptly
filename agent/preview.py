import base64
import json
import re
from pathlib import PurePosixPath


def _normalize_path(path: str) -> str:
    return str(PurePosixPath(path.replace("\\", "/")))


def _resolve_path(base_file: str, href: str) -> str:
    href = href.strip()
    if href.startswith(("http://", "https://", "//", "data:", "mailto:", "tel:", "#")):
        return href
    base_dir = str(PurePosixPath(base_file).parent)
    if base_dir == ".":
        return _normalize_path(href)
    return _normalize_path(str(PurePosixPath(base_dir) / href))


def _inline_css_urls(css: str, files: dict[str, str], css_path: str) -> str:
    def replace_url(match: re.Match) -> str:
        raw = match.group(1).strip("'\"")
        if raw.startswith(("http://", "https://", "data:", "#")):
            return match.group(0)
        resolved = _resolve_path(css_path, raw)
        asset = files.get(resolved)
        if asset is None:
            return match.group(0)
        if resolved.lower().endswith(".svg"):
            encoded = f"data:image/svg+xml,{asset}"
            return f"url('{encoded}')"
        return match.group(0)

    return re.sub(r"url\(\s*['\"]?([^)'\"]+)['\"]?\s*\)", replace_url, css, flags=re.IGNORECASE)


def _inline_css_imports(css: str, files: dict[str, str], css_path: str) -> str:
    def replace_import(match: re.Match) -> str:
        import_path = _resolve_path(css_path, match.group(1).strip("'\" "))
        imported = files.get(import_path, "")
        if not imported:
            return match.group(0)
        imported = _inline_css_imports(imported, files, import_path)
        return _inline_css_urls(imported, files, import_path)

    return re.sub(r"@import\s+['\"]([^'\"]+)['\"]\s*;", replace_import, css, flags=re.IGNORECASE)


def _inline_assets(html: str, files: dict[str, str], page_path: str) -> str:
    normalized = {_normalize_path(k): v for k, v in files.items()}

    def replace_stylesheet(match: re.Match) -> str:
        tag = match.group(0)
        href_match = re.search(r'href=["\']([^"\']+)["\']', tag, re.IGNORECASE)
        if not href_match:
            return tag
        href = href_match.group(1)
        if not href.lower().endswith(".css") and "stylesheet" not in tag.lower():
            return tag
        resolved = _resolve_path(page_path, href)
        css = normalized.get(resolved)
        if not css:
            return tag
        css = _inline_css_imports(css, normalized, resolved)
        css = _inline_css_urls(css, normalized, resolved)
        return f"<style data-promptly=\"css\">\n{css}\n</style>"

    def replace_script(match: re.Match) -> str:
        tag = match.group(0)
        src_match = re.search(r'src=["\']([^"\']+)["\']', tag, re.IGNORECASE)
        if not src_match:
            return tag
        resolved = _resolve_path(page_path, src_match.group(1))
        js = normalized.get(resolved)
        if not js:
            return tag
        return f"<script data-promptly=\"js\">\n{js}\n</script>"

    html = re.sub(r"<link\b[^>]*/?>", replace_stylesheet, html, flags=re.IGNORECASE)
    html = re.sub(
        r"<script\b[^>]*\bsrc=[^>]*>\s*</script>",
        replace_script,
        html,
        flags=re.IGNORECASE,
    )
    return html


def _inject_router(page_html: str, pages: dict[str, str], current_page: str) -> str:
    pages_b64 = base64.b64encode(json.dumps(pages).encode("utf-8")).decode("ascii")
    current_json = json.dumps(current_page)

    router = f"""
<script id="promptly-preview-router">
(function() {{
  const PAGES = JSON.parse(atob("{pages_b64}"));
  let currentPage = {current_json};

  function resolvePath(href, base) {{
    if (!href || href.includes("://") || href.startsWith("/")) return null;
    const baseParts = base.split("/");
    baseParts.pop();
    const parts = href.split("/");
    const out = [...baseParts];
    for (const p of parts) {{
      if (p === "..") out.pop();
      else if (p && p !== ".") out.push(p);
    }}
    return out.join("/") || "index.html";
  }}

  function runScripts(scope) {{
    scope.querySelectorAll("script").forEach(function(oldScript) {{
      const script = document.createElement("script");
      if (oldScript.src) script.src = oldScript.src;
      else script.textContent = oldScript.textContent;
      oldScript.replaceWith(script);
    }});
  }}

  function loadPage(target) {{
    const html = PAGES[target];
    if (!html) return;
    const doc = new DOMParser().parseFromString(html, "text/html");

    document.title = doc.title || document.title;
    document.head.querySelectorAll("style[data-promptly], link[rel='stylesheet']").forEach(el => el.remove());
    doc.head.querySelectorAll("style").forEach(el => document.head.appendChild(el.cloneNode(true)));

    document.body.innerHTML = doc.body.innerHTML;
    currentPage = target;
    runScripts(document.body);
  }}

  function navigate(href) {{
    const target = resolvePath(href, currentPage) || href;
    if (PAGES[target]) loadPage(target);
  }}

  document.addEventListener("click", function(e) {{
    const a = e.target.closest("a");
    if (!a) return;
    const href = a.getAttribute("href");
    if (!href || href.startsWith("http") || href.startsWith("mailto:") ||
        href.startsWith("tel:") || href.startsWith("#")) return;
    e.preventDefault();
    e.stopPropagation();
    navigate(href);
  }}, true);
}})();
</script>
"""

    lower = page_html.lower()
    head_end = lower.find("</head>")
    if head_end != -1:
        return page_html[:head_end] + router + "\n" + page_html[head_end:]
    return router + page_html


def _pick_index_page(html_files: list[str]) -> str:
    for name in ("index.html", "Index.html"):
        if name in html_files:
            return name
    return html_files[0]


def build_preview_bundle(files: dict[str, str]) -> dict[str, str]:
    html_files = sorted(path for path in files if path.lower().endswith(".html"))
    if not html_files:
        return {}

    processed = {page: _inline_assets(files[page], files, page) for page in html_files}

    routed = {}
    for page_path, content in processed.items():
        routed[page_path] = _inject_router(content, processed, page_path)

    return routed


def build_preview_html(files: dict[str, str], start_page: str | None = None) -> str:
    bundle = build_preview_bundle(files)
    if not bundle:
        return (
            "<html><body><p style='font-family:sans-serif;color:#666;padding:2rem'>"
            "No preview yet.</p></body></html>"
        )

    page = start_page if start_page in bundle else _pick_index_page(list(bundle.keys()))
    return bundle[page]
