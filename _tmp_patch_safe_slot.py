"""One-shot patcher: add @safe_slot to Qt slot methods, preserving original line endings."""
import re

def patch_file(path, import_anchor, signatures):
    with open(path, "rb") as f:
        data = f.read()
    text = data.decode("latin-1")
    if "from app.utils.safe_slot import safe_slot" in text:
        print(path + ": import already present")
    else:
        ipat = re.compile(r"^(" + re.escape(import_anchor) + r")[ \t]*(\r\n|\n)", re.MULTILINE)
        matches = list(ipat.finditer(text))
        assert len(matches) == 1, "import anchor not unique: " + repr(import_anchor) + " -> " + str(len(matches))
        def irepl(m):
            return m.group(1) + m.group(2) + "from app.utils.safe_slot import safe_slot" + m.group(2)
        text, n = ipat.subn(irepl, text, count=1)
        assert n == 1, "failed to insert import in " + path
    for sig in signatures:
        spat = re.compile(r"^([ \t]*)(" + re.escape(sig) + r")[ \t]*(\r\n|\n)", re.MULTILINE)
        matches = list(spat.finditer(text))
        assert len(matches) == 1, "signature not unique: " + repr(sig) + " -> " + str(len(matches))
        def srepl(m):
            indent, line, nl = m.group(1), m.group(2), m.group(3)
            return indent + "@safe_slot" + nl + indent + line + nl
        text, n = spat.subn(srepl, text, count=1)
        assert n == 1, "failed to patch " + repr(sig) + " in " + path
    new_data = text.encode("latin-1")
    with open(path, "wb") as f:
        f.write(new_data)
    print(path + ": patched " + str(len(signatures)) + " slots, size " + str(len(data)) + " -> " + str(len(new_data)))

patch_file(r"d:\desktop\project\UniversalCrawlerProplus\app\ui\pages\settings_page.py", "from app.utils.qt_runtime import load_qt_icon", ["def _run_pending_relayout(self) -> None:", "def _repair_empty_view_if_needed(self) -> None:", "def _refresh_theme_widgets(self) -> None:"])
patch_file(r"d:\desktop\project\UniversalCrawlerProplus\app\ui\pages\log_center_page.py", "from app.ui.styles.themes import resolve_is_dark_theme, theme_colors", ["def _refresh_log_center_visual_state(self) -> None:", "def _on_page_size_changed(self, text: str) -> None:", "def _go_prev_page(self) -> None:", "def _go_next_page(self) -> None:", "def _copy_current_trace_id(self) -> None:", "def _copy_current_log_json(self) -> None:", "def _copy_current_log_detail(self) -> None:", "def _export_current_log_detail(self) -> None:", "def _resize_detail_message_box(self) -> None:", "def _resize_json_viewer_to_content(self) -> None:"])
print("DONE")