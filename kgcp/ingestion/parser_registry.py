"""Parser registry — maps file extensions to parser functions."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# Parser function signature: (file_path: Path) -> str
ParserFn = Callable[[Path], str]

_REGISTRY: dict[str, ParserFn] = {}


def register_parser(extensions: list[str], parser_fn: ParserFn) -> None:
    """Register a parser function for one or more file extensions."""
    for ext in extensions:
        ext = ext.lower().lstrip(".")
        _REGISTRY[ext] = parser_fn
        logger.debug("Registered parser for .%s", ext)


def get_parser(file_path: str | Path) -> ParserFn | None:
    """Get the appropriate parser for a file."""
    ext = Path(file_path).suffix.lower().lstrip(".")
    return _REGISTRY.get(ext)


def supported_extensions() -> list[str]:
    """Return list of supported file extensions."""
    return sorted(_REGISTRY.keys())


def parse_file(file_path: str | Path) -> str:
    """Parse a file using the registered parser for its extension.

    Falls back to plaintext reading if no specific parser is registered.

    Raises:
        FileNotFoundError: If file doesn't exist.
        ValueError: If file type is not supported and cannot be read as text.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    parser = get_parser(path)
    if parser:
        return parser(path)

    # Fallback: try reading as plain text
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ValueError(
            f"Cannot parse {path.suffix} files. "
            f"Supported extensions: {', '.join(supported_extensions())}"
        )


# -- Register built-in parsers ------------------------------------------------

def _parse_plaintext(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_markdown(path: Path) -> str:
    """Parse Markdown, stripping formatting artifacts."""
    import re
    text = path.read_text(encoding="utf-8")
    # Remove image references
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    # Convert headers to plain text with newlines
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Remove link formatting but keep text
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    # Remove bold/italic markers
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", text)
    # Remove code block markers
    text = re.sub(r"```\w*\n?", "", text)
    return text.strip()


def _parse_html(path: Path) -> str:
    """Parse HTML to plain text."""
    try:
        import html2text
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        return h.handle(path.read_text(encoding="utf-8"))
    except ImportError:
        # Fallback: strip tags manually
        import re
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()


def _parse_pdf(path: Path) -> str:
    """Parse PDF to plain text using PyMuPDF."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(path))
        pages = []
        for page in doc:
            pages.append(page.get_text())
        doc.close()
        return "\n\n".join(pages)
    except ImportError:
        raise ImportError(
            "PyMuPDF is required for PDF parsing. "
            "Install with: pip install PyMuPDF"
        )


def _parse_code(path: Path) -> str:
    """Parse source code files — keep as-is with a header."""
    text = path.read_text(encoding="utf-8")
    return f"Source file: {path.name}\n\n{text}"


# Register all built-in parsers
register_parser(["txt", "text", "log", "csv"], _parse_plaintext)
register_parser(["md", "markdown", "rst"], _parse_markdown)
register_parser(["html", "htm"], _parse_html)
register_parser(["pdf"], _parse_pdf)
register_parser(
    ["py", "js", "ts", "java", "go", "rs", "c", "cpp", "h", "rb", "sh", "yaml", "yml", "toml", "json"],
    _parse_code,
)
