"""Output utilities — stdout, clipboard, file writing."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from ..models import PackedContext


def output_context(
    ctx: PackedContext,
    to_clipboard: bool = False,
    to_file: str | None = None,
) -> None:
    """Write packed context to the appropriate destination."""
    if to_file:
        path = Path(to_file).expanduser()
        path.write_text(ctx.content)
        print(f"Written to {path} ({ctx.token_count} tokens, {ctx.triplet_count} triplets)")
        return

    if to_clipboard:
        try:
            proc = subprocess.run(
                ["pbcopy"],  # macOS
                input=ctx.content.encode(),
                check=True,
            )
            print(f"Copied to clipboard ({ctx.token_count} tokens, {ctx.triplet_count} triplets)")
            return
        except (FileNotFoundError, subprocess.CalledProcessError):
            try:
                proc = subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=ctx.content.encode(),
                    check=True,
                )
                print(f"Copied to clipboard ({ctx.token_count} tokens, {ctx.triplet_count} triplets)")
                return
            except (FileNotFoundError, subprocess.CalledProcessError):
                print("Clipboard not available, printing to stdout instead.", file=sys.stderr)

    # Default: stdout
    print(ctx.content)
