#!/usr/bin/env python3
"""Compute dependency graph function LOC statistics from parsed project info."""

import argparse
import csv
import os
import re
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


def parse_entity_token(token: str) -> Optional[Tuple[str, str, int, str]]:
    token = token.strip()
    if not token:
        return None
    if token.count("#") < 2:
        return None
    name, filename, line_no = token.rsplit("#", 2)
    line_no = line_no.strip()
    match = re.match(r"^(\d+)$", line_no)
    if not match:
        return None
    return name, filename, int(line_no), token


def parse_project_info(path: Path) -> Tuple[Dict[str, Dict], Dict[str, List[str]]]:
    entries: Dict[str, Dict] = {}
    edges: Dict[str, List[str]] = {}
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue

            if "<->" in line:
                tokens = [t.strip() for t in re.split(r"\s*<->\s*", line) if t.strip()]
                parsed_tokens = [parse_entity_token(t) for t in tokens]
                if any(t is None for t in parsed_tokens):
                    continue
                keys = []
                for name, filename, line_no, raw_token in parsed_tokens:
                    key = f"{name}#{filename}#{line_no}"
                    keys.append((key, name, filename, line_no, raw_token))
                    if key not in entries:
                        entries[key] = {
                            "name": name,
                            "filename": filename,
                            "line": line_no,
                            "raw": raw_token,
                        }
                        edges[key] = []
                for i in range(len(keys) - 1):
                    a = keys[i][0]
                    b = keys[i + 1][0]
                    if b not in edges[a]:
                        edges[a].append(b)
                    if a not in edges[b]:
                        edges[b].append(a)
                continue

            if "->" not in line:
                continue

            parts = re.split(r"\s*->\s*", line, maxsplit=1)
            if len(parts) < 2:
                continue
            left = parts[0].strip()
            right = parts[1].strip()
            left_entry = parse_entity_token(left)
            if left_entry is None:
                continue
            name, filename, line_no, raw_token = left_entry
            key = f"{name}#{filename}#{line_no}"
            deps = [d.strip() for d in right.split(",") if d.strip()]
            valid_deps = []
            for dep in deps:
                dep_entry = parse_entity_token(dep)
                if dep_entry is None:
                    continue
                dep_name, dep_filename, dep_line_no, dep_raw = dep_entry
                dep_key = f"{dep_name}#{dep_filename}#{dep_line_no}"
                valid_deps.append(dep_key)
                if dep_key not in entries:
                    entries[dep_key] = {
                        "name": dep_name,
                        "filename": dep_filename,
                        "line": dep_line_no,
                        "raw": dep_raw,
                    }
                    edges[dep_key] = []
            if key not in entries:
                entries[key] = {
                    "name": name,
                    "filename": filename,
                    "line": line_no,
                    "raw": raw_token,
                }
            edges[key] = valid_deps
    return entries, edges


def build_filename_index(source_root: Path) -> Dict[str, List[Path]]:
    index = defaultdict(list)
    for path in source_root.rglob("*"):
        if path.is_file() and path.suffix in {".c", ".h", ".cpp", ".cc", ".cxx", ".hpp"}:
            index[path.name].append(path)
    return index


def choose_source_path(candidates: Sequence[Path], line_no: int) -> Optional[Path]:
    valid = [p for p in candidates if p.exists() and sum(1 for _ in p.open("r", encoding="utf-8", errors="replace")) >= line_no]
    if not valid:
        return None
    # Prefer candidate with smallest sufficient length so the line mapping is more likely to be exact.
    valid.sort(key=lambda p: (sum(1 for _ in p.open("r", encoding="utf-8", errors="replace")), str(p)))
    return valid[0]


def read_source_lines(path: Path) -> List[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def normalize_name_for_regex(name: str) -> str:
    return re.escape(name)


def is_definitely_function(lines: List[str], start_idx: int, name: str) -> Optional[int]:
    # Find a function header or opening brace after start_idx.
    # Return index of the line containing '{' for the function body, or None.
    # Search through the next 20 lines at most.
    text = []
    for idx in range(start_idx, min(start_idx + 30, len(lines))):
        text.append(lines[idx])
        joined = " ".join(text)
        if "(" in joined and name in joined:
            # Don't treat macros or declarations with semicolon as function definitions.
            if ";" in joined and joined.index(";") < joined.index("{") if "{" in joined else False:
                return None
        if "{" in lines[idx]:
            header = " ".join(text)
            if re.search(r"\b" + normalize_name_for_regex(name) + r"\b\s*\(", header):
                return idx
    return None


def find_matching_brace(lines: List[str], start_idx: int, brace_pos: int) -> Optional[int]:
    stack = 0
    i = start_idx
    state = "normal"
    escape = False
    while i < len(lines):
        line = lines[i]
        j = 0
        while j < len(line):
            ch = line[j]
            nxt = line[j + 1] if j + 1 < len(line) else ""
            if state == "normal":
                if ch == "/" and nxt == "*":
                    state = "comment"
                    j += 1
                elif ch == "/" and nxt == "/":
                    break
                elif ch == '"':
                    state = "string"
                elif ch == "'":
                    state = "char"
                elif ch == "{":
                    if i == start_idx and j < brace_pos or i > start_idx:
                        stack += 1
                elif ch == "}":
                    if stack <= 0:
                        return i
                    stack -= 1
            elif state == "comment":
                if ch == "*" and nxt == "/":
                    state = "normal"
                    j += 1
            elif state == "string":
                if ch == "\\" and not escape:
                    escape = True
                elif ch == '"' and not escape:
                    state = "normal"
                else:
                    escape = False
            elif state == "char":
                if ch == "\\" and not escape:
                    escape = True
                elif ch == "'" and not escape:
                    state = "normal"
                else:
                    escape = False
            j += 1
        i += 1
    return None


def line_count_for_function(lines: List[str], start_idx: int, name: str) -> Optional[int]:
    header_line = is_definitely_function(lines, start_idx, name)
    if header_line is None:
        return None
    brace_pos = lines[header_line].find("{")
    if brace_pos < 0:
        # Search the header lines for an opening brace, then start from there.
        for idx in range(start_idx, header_line + 1):
            if "{" in lines[idx]:
                brace_pos = lines[idx].find("{")
                header_line = idx
                break
    if brace_pos < 0:
        return None
    end_idx = find_matching_brace(lines, header_line, brace_pos)
    if end_idx is None:
        return None
    return end_idx - start_idx + 1


def compute_function_spans(entries: Dict[str, Dict], source_root: Path) -> Dict[str, int]:
    filename_index = build_filename_index(source_root)
    source_cache: Dict[Path, List[str]] = {}
    function_loc: Dict[str, int] = {}

    for key, entry in entries.items():
        filename = entry["filename"]
        line_no = entry["line"]
        candidates = filename_index.get(filename, [])
        if not candidates:
            continue
        source_path = choose_source_path(candidates, line_no)
        if source_path is None:
            continue
        if source_path not in source_cache:
            source_cache[source_path] = read_source_lines(source_path)
        lines = source_cache[source_path]
        start_idx = line_no - 1
        if start_idx < 0 or start_idx >= len(lines):
            continue
        loc = line_count_for_function(lines, start_idx, entry["name"])
        if loc is not None and loc > 0:
            function_loc[key] = loc
    return function_loc


def compute_graph_totals(entries: Dict[str, Dict], edges: Dict[str, List[str]], function_loc: Dict[str, int]) -> Dict[str, Dict[str, int]]:
    memo = {}

    def closure(start_key: str) -> Tuple[int, int, int]:
        if start_key in memo:
            return memo[start_key]
        visited = set()
        stack = [start_key]
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            for dep in edges.get(node, []):
                if dep not in visited:
                    stack.append(dep)
        total_loc = sum(function_loc.get(node, 0) for node in visited)
        function_count = sum(1 for node in visited if node in function_loc)
        memo[start_key] = (total_loc, function_count, len(visited))
        return memo[start_key]

    totals = {}
    for key in entries:
        total_loc, function_count, closure_size = closure(key)
        totals[key] = {
            "total_loc": total_loc,
            "function_count": function_count,
            "closure_size": closure_size,
        }
    return totals


def histogram(values: Sequence[int], bucket_size: int = 100) -> Counter:
    buckets = Counter()
    for value in values:
        if value < 0:
            bucket_name = "negative"
        else:
            lower = (value // bucket_size) * bucket_size
            upper = lower + bucket_size
            bucket_name = f"{lower}-{upper}"
        buckets[bucket_name] += 1
    return buckets


def write_csv(path: Path, entries: Dict[str, Dict], totals: Dict[str, Dict[str, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([
            "entity",
            "filename",
            "line",
            "total_graph_function_loc",
            "function_nodes_in_graph",
            "dependency_closure_size",
        ])
        for key, entry in entries.items():
            row = [
                key,
                entry["filename"],
                entry["line"],
                totals[key]["total_loc"],
                totals[key]["function_count"],
                totals[key]["closure_size"],
            ]
            writer.writerow(row)


def write_histogram(path: Path, hist: Counter) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for bucket in sorted(hist.keys(), key=lambda x: (int(x.split("-")[0]) if "-" in x else float('inf'))):
            f.write(f"{bucket}: {hist[bucket]}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute LOC statistics for entity dependency graphs.")
    parser.add_argument("--project-info", default="dataset/parsed_projects/sqlite_ProjectInfo.txt",
                        help="Path to the parsed project info file.")
    parser.add_argument("--source-root", default=".", help="Root path for source file search.")
    parser.add_argument("--output-csv", default="dataset/parsed_projects/sqlite_entity_graph_loc_stats.csv",
                        help="Output CSV file path.")
    parser.add_argument("--output-ranges", default="dataset/parsed_projects/sqlite_entity_graph_loc_ranges.txt",
                        help="Output histogram file path.")
    parser.add_argument("--bucket-size", type=int, default=100, help="Bucket size for range statistics.")
    args = parser.parse_args()

    project_info_path = Path(args.project_info)
    source_root = Path(args.source_root)
    output_csv = Path(args.output_csv)
    output_ranges = Path(args.output_ranges)

    entries, edges = parse_project_info(project_info_path)
    function_loc = compute_function_spans(entries, source_root)
    totals = compute_graph_totals(entries, edges, function_loc)
    write_csv(output_csv, entries, totals)
    hist = histogram([totals[key]["total_loc"] for key in entries], bucket_size=args.bucket_size)
    write_histogram(output_ranges, hist)

    print(f"Wrote graph LOC stats to {output_csv}")
    print(f"Wrote range histogram to {output_ranges}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
