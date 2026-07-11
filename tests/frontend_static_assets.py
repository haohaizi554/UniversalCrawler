from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = PROJECT_ROOT / "app" / "web" / "static"


class _StaticAssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stylesheets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "link":
            return
        values = {name.casefold(): value or "" for name, value in attrs}
        if values.get("rel", "").casefold() != "stylesheet":
            return
        href = values.get("href", "")
        if href:
            self.stylesheets.append(href)


def stylesheet_names_from_index() -> tuple[str, ...]:
    parser = _StaticAssetParser()
    parser.feed((STATIC_DIR / "index.html").read_text(encoding="utf-8"))
    return tuple(Path(href.split("?", 1)[0]).name for href in parser.stylesheets)


def stylesheet_paths_from_index() -> tuple[Path, ...]:
    return tuple(STATIC_DIR / name for name in stylesheet_names_from_index())


def css_bundle_from_index() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in stylesheet_paths_from_index())
