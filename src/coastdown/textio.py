"""Deterministic text output helpers."""

from __future__ import annotations

from pathlib import Path


def write_text_lf(path: Path, text: str) -> None:
    """Write UTF-8 text with LF line endings on every platform.

    ``Path.write_text`` applies the platform newline translation, so the same
    generator emits CRLF on Windows and LF on Linux.  Published artifacts carry
    byte sizes and SHA-256 digests, so a newline must never depend on the
    machine that produced the file.
    """
    path.write_text(text, encoding="utf-8", newline="\n")
