"""Offline chunking of our Markdown policies; sizes are characters, not tokens.

Tables are atomic and may exceed max_chars; oversized=True makes this exception
explicit. No overlap is added. Only docs/policies is included by the CLI.
"""

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Chunk:
    source: str
    title: str
    section: str
    body: str
    text: str
    oversized: bool


def _sections(markdown: str, title: str):
    headings = {}
    lines = []
    section = "Introduction"
    for line in markdown.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if match:
            if lines:
                yield section, lines
                lines = []
            level, heading = len(match[1]), match[2]
            headings = {k: v for k, v in headings.items() if k < level}
            if level > 1:
                headings[level] = heading
            section = " > ".join(headings.values()) or "Introduction"
        else:
            lines.append(line)
    if lines:
        yield section, lines


def _blocks(lines):
    """Keep consecutive pipe-prefixed rows together, even without blank lines."""
    current = []
    table = False
    for line in lines:
        is_table = line.lstrip().startswith("|")
        starts_item = re.match(r"^\s*(?:[-+*]|\d+[.)])\s+", line) is not None
        if not line.strip() or (current and (is_table != table or starts_item)):
            if current:
                yield table, "\n".join(current).strip()
                current = []
        if line.strip():
            current.append(line)
            table = is_table
    if current:
        yield table, "\n".join(current).strip()


def _split_text(text: str, capacity: int):
    while len(text) > capacity:
        # Prefer whitespace; fall back to cutting a single overlong word.
        cuts = [m.start() for m in re.finditer(r"\s", text[:capacity + 1])]
        cut = cuts[-1] if cuts and cuts[-1] > 0 else capacity
        yield text[:cut].rstrip()
        text = text[cut:].lstrip()
    if text:
        yield text


def chunk_markdown(markdown: str, source: str, max_chars: int = 1200) -> list[Chunk]:
    """Prefix every chunk with source, document title and nested section path.

    Supports the ATX headings and pipe tables used by this policy corpus;
    this is not a general Markdown parser (e.g. fenced code is unsupported).
    The cap includes the prefix. Only an indivisible table may exceed it.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    heading = re.search(r"^#\s+(.+?)\s*#*\s*$", markdown, re.MULTILINE)
    title = heading[1] if heading else Path(source).stem
    chunks = []
    for section, lines in _sections(markdown, title):
        prefix = f"Source: {source}\nTitle: {title}\nSection: {section}\n\n"
        capacity = max_chars - len(prefix)
        if capacity <= 0:
            raise ValueError("max_chars must leave room for content after the prefix")
        pending = ""

        def emit(body):
            if body:
                text = prefix + body
                chunks.append(Chunk(source, title, section, body, text, len(text) > max_chars))

        for table, block in _blocks(lines):
            if table:
                emit(pending)
                pending = ""
                emit(block)
                continue
            for piece in _split_text(block, capacity):
                combined = pending + "\n\n" + piece if pending else piece
                if len(combined) > capacity:
                    emit(pending)
                    pending = piece
                else:
                    pending = combined
        emit(pending)
    return chunks


def main() -> None:
    directory = Path(__file__).resolve().parent / "docs" / "policies"
    files = sorted(directory.glob("*.md"))
    if not files:
        raise SystemExit("No policy documents found")
    all_chunks = []
    for path in files:
        chunks = chunk_markdown(path.read_text(encoding="utf-8"), path.name)
        all_chunks.extend(chunks)
        sizes = [len(c.text) for c in chunks]
        print(f"{path.name}: {len(chunks)} chunks; min={min(sizes, default=0)}; avg={sum(sizes) / len(sizes) if sizes else 0:.1f}; max={max(sizes, default=0)}; oversized={sum(c.oversized for c in chunks)}")
    print(f"Total: {len(files)} files, {len(all_chunks)} chunks")
    if all_chunks:
        sizes = [len(c.text) for c in all_chunks]
        print(f"Overall characters including prefix: min={min(sizes)}; avg={sum(sizes) / len(sizes):.1f}; max={max(sizes)}")
        print("Short chunks (body < 200 characters; review threshold, not minimum size):")
        for index, chunk in enumerate(all_chunks, 1):
            if len(chunk.body) < 200:
                print(f"  {index}: {chunk.source} / {chunk.section}: body={len(chunk.body)}, total={len(chunk.text)}")
        print("\nFirst chunk:\n" + all_chunks[0].text)


if __name__ == "__main__":
    main()
