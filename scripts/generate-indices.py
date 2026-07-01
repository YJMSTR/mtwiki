#!/usr/bin/env python3
"""
generate-indices.py — Auto-generate cross-reference indices for the MT RTL Optimizer Wiki.

Usage:
    python scripts/generate-indices.py              # regenerate all indices
    python scripts/generate-indices.py --search "lock-free"   # search wiki + sources
    python scripts/generate-indices.py --tag "hpc"  # list pages by tag
"""

import os
import sys
import re
import yaml
import argparse
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# ── Config ───────────────────────────────────────────────────────────────────
WIKI_ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = WIKI_ROOT / "sources"
WIKI_DIR    = WIKI_ROOT / "wiki"
QUERIES_DIR = WIKI_ROOT / "queries"

YAML_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# ── Helpers ──────────────────────────────────────────────────────────────────

def extract_frontmatter(text: str) -> dict:
    """Parse YAML frontmatter from markdown text."""
    m = YAML_FRONTMATTER_RE.match(text)
    if m:
        try:
            return yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            return {}
    return {}

def list_markdown_files(directory: Path):
    """Yield all .md files under directory, skipping templates."""
    if not directory.exists():
        return
    for path in directory.rglob("*.md"):
        if path.name.startswith("_"):
            continue
        yield path

def read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def make_id(path: Path, category: str) -> str:
    """Generate a stable id like 'wiki-parallel-pdes' or 'source-verilator-mt'."""
    category_dir = "sources" if category == "source" else category
    rel = path.relative_to(WIKI_ROOT / category_dir)
    stem = rel.with_suffix("").as_posix().replace("/", "-")
    return f"{category}-{stem}"

# ── Index Builders ───────────────────────────────────────────────────────────

def build_indices():
    """Scan sources/ and wiki/, build all indices."""
    
    # Data structures
    by_tag = defaultdict(list)          # tag -> [(id, title, path, excerpt)]
    by_source = defaultdict(list)       # source_id -> [(id, title, path, type)]
    by_keyword = defaultdict(list)      # keyword -> [(id, title, path, context)]
    all_entries = []                    # all entries for search
    
    # ── Scan sources ──
    for path in list_markdown_files(SOURCES_DIR):
        text = read_file(path)
        fm = extract_frontmatter(text)
        
        entry_id = make_id(path, "source")
        title = fm.get("title", path.stem)
        source_url = fm.get("source_url", "")
        source_type = fm.get("source_type", "unknown")
        tags = fm.get("tags", [])
        keywords = fm.get("keywords", [])
        
        entry = {
            "id": entry_id,
            "title": title,
            "path": str(path.relative_to(WIKI_ROOT).as_posix()),
            "type": "source",
            "source_url": source_url,
            "source_type": source_type,
            "tags": tags,
            "keywords": keywords,
        }
        all_entries.append(entry)
        
        for tag in tags:
            by_tag[tag].append((entry_id, title, entry["path"], "source"))
        for kw in keywords:
            by_keyword[kw].append((entry_id, title, entry["path"], "source"))
    
    # ── Scan wiki ──
    for path in list_markdown_files(WIKI_DIR):
        text = read_file(path)
        fm = extract_frontmatter(text)
        
        entry_id = make_id(path, "wiki")
        title = fm.get("title", path.stem)
        tags = fm.get("tags", [])
        keywords = fm.get("keywords", [])
        related_sources = fm.get("related_sources", [])
        
        entry = {
            "id": entry_id,
            "title": title,
            "path": str(path.relative_to(WIKI_ROOT).as_posix()),
            "type": "wiki",
            "tags": tags,
            "keywords": keywords,
            "related_sources": related_sources,
        }
        all_entries.append(entry)
        
        for tag in tags:
            by_tag[tag].append((entry_id, title, entry["path"], "wiki"))
        for kw in keywords:
            by_keyword[kw].append((entry_id, title, entry["path"], "wiki"))
        
        for src_id in related_sources:
            by_source[src_id].append((entry_id, title, entry["path"], "wiki"))
    
    # ── Write indices ──
    QUERIES_DIR.mkdir(parents=True, exist_ok=True)
    
    # by-tag.md
    with open(QUERIES_DIR / "by-tag.md", "w", encoding="utf-8") as f:
        f.write("---\n")
        f.write("title: Index by Tag\n")
        f.write(f"generated: {datetime.now().isoformat()}\n")
        f.write("---\n\n")
        f.write("# Index by Tag\n\n")
        for tag in sorted(by_tag.keys()):
            f.write(f"## {tag}\n\n")
            for eid, title, epath, etype in sorted(by_tag[tag]):
                f.write(f"- [{title}]({WIKI_ROOT / epath}) `{'source' if etype == 'source' else 'wiki'}`\n")
            f.write("\n")
    
    # by-source.md
    with open(QUERIES_DIR / "by-source.md", "w", encoding="utf-8") as f:
        f.write("---\n")
        f.write("title: Index by Source\n")
        f.write(f"generated: {datetime.now().isoformat()}\n")
        f.write("---\n\n")
        f.write("# Index by Source\n\n")
        for src_id in sorted(by_source.keys()):
            f.write(f"## {src_id}\n\n")
            for eid, title, epath, etype in sorted(by_source[src_id]):
                f.write(f"- [{title}]({WIKI_ROOT / epath}) `wiki`\n")
            f.write("\n")
    
    # by-keyword.md
    with open(QUERIES_DIR / "by-keyword.md", "w", encoding="utf-8") as f:
        f.write("---\n")
        f.write("title: Index by Keyword\n")
        f.write(f"generated: {datetime.now().isoformat()}\n")
        f.write("---\n\n")
        f.write("# Index by Keyword\n\n")
        for kw in sorted(by_keyword.keys()):
            f.write(f"## {kw}\n\n")
            for eid, title, epath, etype in sorted(by_keyword[kw]):
                f.write(f"- [{title}]({WIKI_ROOT / epath}) `{'source' if etype == 'source' else 'wiki'}`\n")
            f.write("\n")
    
    # all-entries.json
    import json
    with open(QUERIES_DIR / "all-entries.json", "w", encoding="utf-8") as f:
        json.dump(all_entries, f, indent=2, ensure_ascii=False)
    
    print(f"[Indices] {len(all_entries)} entries indexed.")
    print(f"  Tags: {len(by_tag)}")
    print(f"  Keywords: {len(by_keyword)}")
    print(f"  Source refs: {len(by_source)}")
    print(f"  Output: {QUERIES_DIR}")

def do_search(query: str):
    """Search across all entries by title, tag, keyword, and content."""
    import json
    
    query_lower = query.lower()
    results = []
    
    json_path = QUERIES_DIR / "all-entries.json"
    if json_path.exists():
        with open(json_path, encoding="utf-8") as f:
            all_entries = json.load(f)
    else:
        print("Error: Index not built yet. Run without --search first.")
        sys.exit(1)
    
    # Also search content
    for entry in all_entries:
        score = 0
        text = f"{entry.get('title','')} {' '.join(entry.get('tags',[]))} {' '.join(entry.get('keywords',[]))}"
        text_lower = text.lower()
        
        # Read content if needed
        content_path = WIKI_ROOT / entry["path"]
        content = ""
        if content_path.exists():
            content = content_path.read_text(encoding="utf-8").lower()
        
        if query_lower in entry.get("title", "").lower():
            score += 10
        if any(query_lower in t.lower() for t in entry.get("tags", [])):
            score += 8
        if any(query_lower in k.lower() for k in entry.get("keywords", [])):
            score += 6
        if query_lower in content:
            score += 3
        
        if score > 0:
            results.append((score, entry))
    
    results.sort(key=lambda x: -x[0])
    
    print(f"\nSearch results for '{query}' ({len(results)} hits):\n")
    for score, entry in results[:30]:
        print(f"  [{entry['type']}] {entry['title']} (score={score})")
        print(f"    Path: {entry['path']}")
        tags = entry.get("tags", [])
        if tags:
            print(f"    Tags: {', '.join(tags)}")
        kws = entry.get("keywords", [])
        if kws:
            print(f"    Keywords: {', '.join(kws)}")
        print()

def do_list_tag(tag: str):
    """List all entries with a specific tag."""
    import json
    
    json_path = QUERIES_DIR / "all-entries.json"
    if not json_path.exists():
        print("Error: Index not built yet. Run without --tag first.")
        sys.exit(1)
    
    with open(json_path, encoding="utf-8") as f:
        all_entries = json.load(f)
    
    matches = [e for e in all_entries if tag in [t.lower() for t in e.get("tags", [])]]
    
    print(f"\nEntries with tag '{tag}' ({len(matches)}):\n")
    for entry in matches:
        print(f"  [{entry['type']}] {entry['title']}")
        print(f"    Path: {entry['path']}")
        print()

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Wiki cross-reference index generator")
    parser.add_argument("--search", type=str, help="Search query string")
    parser.add_argument("--tag", type=str, help="List entries by tag")
    args = parser.parse_args()
    
    if args.search:
        do_search(args.search)
    elif args.tag:
        do_list_tag(args.tag)
    else:
        build_indices()

if __name__ == "__main__":
    main()
