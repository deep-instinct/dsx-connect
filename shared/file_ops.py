from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import io
import os
import pathlib
import shutil
import shlex
import time
from pathlib import Path, PurePosixPath
from typing import AsyncGenerator, Iterable, Iterator, List, Optional, Set, Tuple

from shared.dsx_logging import dsx_logging


# =========================
# Basic file helpers (kept)
# =========================

def calculate_sha256_from_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def calculate_sha256_from_bytesio(file_obj: io.BytesIO, chunk_size: int = 8192) -> str:
    file_obj.seek(0)
    h = hashlib.sha256()
    while True:
        chunk = file_obj.read(chunk_size)
        if not chunk:
            break
        h.update(chunk)
    file_obj.seek(0)
    return h.hexdigest()


def calculate_sha256(filename: str | os.PathLike, chunk_size: int = 8192) -> str:
    h = hashlib.sha256()
    with open(filename, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_file(source_file: str | os.PathLike, dest_file: str | os.PathLike) -> None:
    dest_dir = os.path.dirname(str(dest_file))
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)
    shutil.copy2(source_file, dest_file)


def copy_files_recursively(
        source_dir: str | os.PathLike,
        destination_dir: str | os.PathLike,
        file_exclusions: Optional[Iterable[str]] = None,
) -> None:
    """
    Copy tree from source_dir to destination_dir, skipping files matching any of the
    fnmatch-style patterns in file_exclusions.
    """
    src = Path(source_dir)
    dst = Path(destination_dir)
    patterns = tuple(file_exclusions or ())

    for root, subdirs, files in os.walk(src):
        root_p = Path(root)
        rel = root_p.relative_to(src)
        target_root = dst / rel

        for name in files:
            rel_file_posix = (rel / name).as_posix()
            if any(fnmatch.fnmatch(rel_file_posix, pat) for pat in patterns):
                continue
            target_root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root_p / name, target_root / name)


async def read_file_async(filename: str | os.PathLike, chunk_size: int = -1) -> io.BytesIO:
    """
    Asynchronously read a file into BytesIO. Uses a thread so the event loop isn't blocked.
    """
    data = await asyncio.to_thread(_read_file_blocking, Path(filename), chunk_size)
    return data


def _read_file_blocking(filepath: Path, chunk_size: int = -1) -> io.BytesIO:
    b = io.BytesIO()
    with open(filepath, "rb") as f:
        if chunk_size and chunk_size > 0:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                b.write(chunk)
        else:
            b.write(f.read())
    b.seek(0)
    return b


def read_file(filepath: Path, chunk_size: int = -1) -> io.BytesIO:
    return _read_file_blocking(filepath, chunk_size)


def validate_filepath(path: Path) -> bool:
    """
    Basic path sanity: exists, readable, not a broken symlink.
    """
    try:
        return path.exists() and os.access(path, os.R_OK)
    except Exception:
        return False


# =======================================
# Include/Exclude parsing (rsync/find-ish)
# =======================================

_GLOB_CHARS = set("*?[]")

def _has_glob(s: str) -> bool:
    return any(c in s for c in _GLOB_CHARS)

def _split_tokens(filter_str: str) -> List[str]:
    # Shell-style tokenization: quotes/backslashes preserve spaces.
    return shlex.split(filter_str or "", posix=True)


def _expand_exclude_directive(tokens: List[str]) -> List[str]:
    out, i = [], 0
    while i < len(tokens):
        t = tokens[i]
        if t in ("--exclude", "--include"):
            if i + 1 < len(tokens):
                out.append(("-" if t == "--exclude" else "") + tokens[i+1])
                i += 2
            else:
                i += 1
        elif t.startswith("--exclude=") or t.startswith("--include="):
            k, v = t.split("=", 1)
            out.append(("-" if k == "--exclude" else "") + v)
            i += 1
        else:
            out.append(t)
            i += 1
    return out


def _normalize_include_token(tok: str) -> Tuple[str, ...]:
    """
    - "" or "." handled by caller as include-all.
    - "*" → special: top-level only (handled later).
    - Bare token like 'PDF' → keep literal; treated as base/'PDF' subtree by _expand_includes.
    - 'sub1/*' → keep literal (direct children).
    - Any glob/path (e.g., '**/*.pdf') → keep literal.
    - Comma list like '*.pdf,*.docx' → split by caller before calling this.
    """
    tok = tok.strip().strip("+")
    if tok in ("", "."):
        return ()
    if tok == "*":
        return ("*",)
    return (tok,)

def _normalize_exclude_token(tok: str) -> Tuple[str, ...]:
    tok = tok.strip().lstrip("-")
    if not tok:
        return ()
    if _has_glob(tok) or "/" in tok:
        return (tok,)
    # bare name → any subtree named tok
    return (tok, f"{tok}/**")

def _expand_rsync_dirs(includes: Tuple[str, ...]) -> Tuple[str, ...]:
    out: list[str] = []
    for tok in includes:
        # dir-only (rsync semantics): "foo/" → include all files under it
        if tok.endswith("/") and not tok.endswith("/**") and not tok.endswith("/**/*"):
            root = tok[:-1]
            out.append(root + "/**/*")
        # "foo/**" (rsync): should include files too → make it files-recursive
        elif tok.endswith("/**") and not tok.endswith("/**/*"):
            root = tok[:-3]
            out.extend([root + "/*", root + "/**/*"])  # immediate + deep files
        else:
            out.append(tok)
    return tuple(out)


def parse_filter_spec(filter_str: str) -> Tuple[Tuple[str, ...], Tuple[str, ...], bool, bool]:
    """
    Parse filter string into (includes, excludes, include_all, top_level_only)

    Semantics:
      ""                → include_all=True (scan everything recursively)
      "*"               → top-level files only (no recursion)
      "sub1"            → recurse under base/'sub1'
      "sub1/*"          → direct children of base/'sub1' only
      "*.pdf,*.docx"    → file types anywhere (union)
      "-tmp --exclude cache" → exclude subtrees 'tmp', 'cache' while including everything else
      "reports exports -tmp" → only under 'reports' or 'exports', minus 'tmp'
    """
    raw_tokens = _split_tokens(filter_str)
    tokens = _expand_exclude_directive(raw_tokens)

    includes_acc: List[str] = []
    excludes_acc: List[str] = []

    for raw in tokens:
        if raw.startswith("-"):
            excludes_acc.extend(_normalize_exclude_token(raw))
        else:
            includes_acc.extend(_normalize_include_token(raw))

    includes = tuple(includes_acc)
    excludes = tuple(excludes_acc)
    includes = _expand_rsync_dirs(includes)
    include_all = (len(includes) == 0)
    top_level_only = (not include_all) and (set(includes) == {"*"})

    return includes, excludes, include_all, top_level_only


# ===================================================
# Traversal-first expansion using Path.glob / rglob
# ===================================================

def _split_excludes(excludes: Tuple[str, ...]) -> tuple[set[str], Tuple[str, ...]]:
    bare_dirs: set[str] = set()
    glob_paths: list[str] = []
    for ex in excludes:
        pat = ex.lstrip("-")
        if not pat:
            continue
        if ("/" not in pat) and not any(c in pat for c in "*?[]"):
            bare_dirs.add(pat)
        else:
            glob_paths.append(pat)
    return bare_dirs, tuple(glob_paths)


def _is_excluded_rel(rel_posix: str, glob_paths: Tuple[str, ...]) -> bool:
    p = PurePosixPath(rel_posix)           # enforces path-aware globbing
    return any(p.match(pat) for pat in glob_paths)  # '?' won't match '/'


def _should_descend(dir_abs: Path, base: Path,
                    include_all: bool,
                    include_prefixes: Tuple[str, ...],
                    bare_ex_dirs: set[str],
                    glob_ex_paths: Tuple[str, ...]) -> bool:
    # prune by bare dir name first
    if dir_abs.name in bare_ex_dirs:
        return False
    rel = dir_abs.relative_to(base).as_posix() if dir_abs != base else "."
    # prune by glob/path excludes
    if _is_excluded_rel(rel, glob_ex_paths):
        return False
    if include_all:
        return True
    # descend if this dir is on the path to any include (prefix match)
    prefix = rel.rstrip("/") + "/"
    return any(p.startswith(prefix) or p == rel for p in include_prefixes)


def _expand_includes(base: Path, token: str) -> Iterator[Path]:
    """
    Yield files for a single include token using traversal-first logic.
    """
    if token == "":
        # full recursive
        yield from (p for p in base.rglob("*") if p.is_file())
        return

    if token == "*":
        # top-level only
        yield from (p for p in base.glob("*") if p.is_file())
        return

    # direct-children shorthand: 'sub1/*' with no extra glob chars in 'sub1'
    if token.endswith("/*") and not _has_glob(token[:-2]):
        sub = base / token[:-2]
        if sub.is_dir():
            yield from (p for p in sub.glob("*") if p.is_file())
        elif sub.is_file():
            # odd case 'file/*'
            pass
        return

    # BARE path (no glob chars): treat as subtree RELATIVE to base
    if not _has_glob(token):
        sub = base / token
        if sub.is_dir():
            yield from (p for p in sub.rglob("*") if p.is_file())
        elif sub.is_file():
            yield sub
        return

    # Glob/path pattern (supports '**')
    for p in base.rglob(token):
        if p.is_file():
            yield p


def iter_files(base_dir: str | os.PathLike, filter_str: str) -> Iterator[Path]:
    base = Path(base_dir)
    includes, excludes, include_all, top_level_only = parse_filter_spec(filter_str)

    # If only excludes were given → start from whole tree
    include_tokens: List[str] = list(includes) if not include_all else [""]

    bare_ex_dirs, glob_ex_paths = _split_excludes(excludes)

    # Precompute include prefixes for pruning (dirs only)
    include_prefixes: Tuple[str, ...] = tuple(
        tok.rstrip("/") for tok in include_tokens if tok not in ("", "*")
    )

    seen: set[Path] = set()

    for inc in include_tokens:
        # 1) Empty token → whole tree, with pruning
        if inc == "":
            if top_level_only:
                for p in (q for q in base.glob("*") if q.is_file()):
                    if p not in seen:
                        seen.add(p)
                        yield p
                continue

            for cur, subdirs, files in os.walk(base):
                cur_path = Path(cur)
                # prune subdirs in-place
                keep = []
                for d in subdirs:
                    child = cur_path / d
                    if _should_descend(child, base, True, (), bare_ex_dirs, glob_ex_paths):
                        keep.append(d)
                subdirs[:] = keep

                rel_dir = "." if cur_path == base else cur_path.relative_to(base).as_posix()
                for fname in files:
                    f = cur_path / fname
                    rel = fname if rel_dir == "." else f"{rel_dir}/{fname}"
                    if _is_excluded_rel(rel, glob_ex_paths) or f.parent.name in bare_ex_dirs:
                        continue
                    if f not in seen:
                        seen.add(f)
                        yield f
            continue

        # 2) Top-level only
        if inc == "*":
            for p in (q for q in base.glob("*") if q.is_file()):
                if p not in seen:
                    seen.add(p)
                    yield p
            continue

        # 3) Bare subtree (no glob chars) → walk that subtree
        if not _has_glob(inc) and not inc.endswith("/*"):
            sub = base / inc
            if sub.is_file():
                rel = sub.relative_to(base).as_posix()
                if not _is_excluded_rel(rel, glob_ex_paths) and sub.parent.name not in bare_ex_dirs:
                    if sub not in seen:
                        seen.add(sub); yield sub
                continue
            if not sub.is_dir():
                continue

            for cur, subdirs, files in os.walk(sub):
                cur_path = Path(cur)
                # prune ONLY by excludes (since we're already scoped to the include subtree)
                pruned = []
                for d in subdirs:
                    child = cur_path / d
                    # dir-name exclude
                    if d in bare_ex_dirs:
                        continue
                    # glob/path exclude on the child dir's rel path
                    child_rel = child.relative_to(base).as_posix()
                    if _is_excluded_rel(child_rel, glob_ex_paths):
                        continue
                    pruned.append(d)
                subdirs[:] = pruned

                rel_dir = cur_path.relative_to(base).as_posix()
                for fname in files:
                    f = cur_path / fname
                    rel = f"{rel_dir}/{fname}"
                    if _is_excluded_rel(rel, glob_ex_paths) or f.parent.name in bare_ex_dirs:
                        continue
                    if f not in seen:
                        seen.add(f); yield f
            continue

        # 4) Direct-children form 'sub1/*'
        if inc.endswith("/*") and not _has_glob(inc[:-2]):
            sub = base / inc[:-2]
            if sub.is_dir():
                for f in (q for q in sub.glob("*") if q.is_file()):
                    rel = f.relative_to(base).as_posix()
                    if _is_excluded_rel(rel, glob_ex_paths) or f.parent.name in bare_ex_dirs:
                        continue
                    if f not in seen:
                        seen.add(f); yield f
            continue

        # 5) Glob/path form (supports **)
        for f in base.rglob(inc):
            if not f.is_file():
                continue
            if top_level_only and f.parent != base:
                continue
            rel = f.relative_to(base).as_posix()
            if _is_excluded_rel(rel, glob_ex_paths) or f.parent.name in bare_ex_dirs:
                continue
            if f not in seen:
                seen.add(f); yield f

# ======================
# Sync path enumeration
# ======================

def get_filepaths(path: str | Path, filter_str: str = "") -> List[Path]:
    """
    Return all file paths under 'path' using rsync include/exclude rules.

    Examples:
      ""                        → everything recursively
      "*"                       → top-level files only
      "PDF"                     → only 'PDF' subtree (recursive, base-relative)
      "sub1/*"                  → direct children of sub1 only
      "**/*.pdf"                → all PDFs anywhere
      "PDF -PDF/**/TMP/**"      → PDF subtree but excluding any TMP under it
      "ELFSAMPLES/** -ELFSAMPLES/**/quarantine/**"
    """
    root = Path(path).expanduser()
    if not root.exists():
        return []

    if root.is_file():
        # Evaluate includes/excludes against a single file
        includes, excludes, include_all, _ = parse_filter_spec(filter_str)

        # Treat the file name as the relative path (we don't have a base tree here)
        rel_name = root.name
        rel_full = root.as_posix()  # fallback for patterns containing '/'

        # Excludes: use the new predicate helpers (no _expand_excludes)
        bare_ex_dirs, glob_ex_paths = _split_excludes(excludes)

        # glob/path excludes (e.g., "**/*.bak")
        if _is_excluded_rel(rel_name, glob_ex_paths) or _is_excluded_rel(rel_full, glob_ex_paths):
            return []

        # bare dir excludes aren't really applicable to a single file relative to itself,
        # but if someone passed a deeper file path, also check its parent names:
        try:
            # Walk ancestors and see if any ancestor dir name is bare-excluded
            p = root if root.is_absolute() else root.resolve()
            for ancestor in p.parents:
                if ancestor.name in bare_ex_dirs:
                    return []
        except Exception:
            pass

        # Includes:
        if include_all:
            return [root]

        # A pattern matches if:
        # - "*" (top-level only) → include the file
        # - bare filename equals rel_name
        # - glob without "/" matches rel_name
        # - pattern with "/" matches the full path string
        name_pp = PurePosixPath(rel_name)
        full_pp = PurePosixPath(rel_full)
        for inc in includes:
            if inc in ("", "*"):
                return [root]
            if "/" in inc:
                if full_pp.match(inc):
                    return [root]
                continue
            if not _has_glob(inc):
                if inc == rel_name:
                    return [root]
            else:
                if name_pp.match(inc):
                    return [root]
        return []

    return list(iter_files(root, filter_str))


# ==============================
# Single-path filter evaluation
# ==============================

def path_matches_filter(base_dir: Path | str, file_path: Path | str, filter_str: str = "") -> bool:
    """
    Check if a single file path under base_dir should be included according to
    the rsync-like include/exclude rules used by get_filepaths().

    - base_dir: The root DSXCONNECTOR_ASSET directory.
    - file_path: Absolute or relative path to the file to test.
    - filter_str: DSXCONNECTOR_FILTER string.

    Behavior matches traversal semantics:
      - "" includes everything recursively (subject to excludes).
      - "*" includes only top-level files (direct children of base_dir).
      - Bare token like "sub1" means recurse under base_dir/sub1.
      - "sub1/*" includes only direct children of that subtree.
      - Glob/path patterns (supports **).
      - Excludes apply to any matching path; bare dir excludes apply to any
        ancestor directory with that name.
    """
    base = Path(base_dir).expanduser()
    fp = Path(file_path).expanduser()

    # Ensure the path is inside base
    try:
        rel = fp.resolve().relative_to(base.resolve()).as_posix()
    except Exception:
        return False

    includes, excludes, include_all, top_level_only = parse_filter_spec(filter_str)
    bare_ex_dirs, glob_ex_paths = _split_excludes(excludes)

    # Apply excludes first
    if _is_excluded_rel(rel, glob_ex_paths):
        return False

    # Bare directory excludes apply if any ancestor directory name matches
    rel_pp = PurePosixPath(rel)
    rel_parts = rel_pp.parts[:-1]  # directories only
    if bare_ex_dirs and any(part in bare_ex_dirs for part in rel_parts):
        return False

    # Include-all cases
    if include_all:
        if top_level_only:
            # Only files directly under base
            return len(rel_pp.parts) == 1
        return True

    # Otherwise, must match at least one include token
    def matches_include(tok: str) -> bool:
        # Top-level only
        if tok == "*":
            return len(rel_pp.parts) == 1

        # Direct-children shorthand 'sub1/*' without glob in parent
        if tok.endswith("/*") and not _has_glob(tok[:-2]):
            parent = tok[:-2].strip("/")
            # Parent must match directories exactly and file must be one level below
            if not parent:
                return len(rel_pp.parts) == 1
            # Expect rel to be 'parent/filename' (exactly two parts if parent has no path)
            parent_parts = PurePosixPath(parent).parts
            return rel_parts == tuple(parent_parts)

        # Bare subtree name (no globs or slashes): any file under that subtree
        if not _has_glob(tok) and "/" not in tok:
            # Accept if rel is in that subtree (e.g., tok == 'sub1' and rel startswith 'sub1/')
            return rel == tok or rel.startswith(tok + "/")

        # General case: treat tok as a glob/path pattern relative to base
        try:
            # Primary check: pattern against relative path
            if rel_pp.match(tok):
                return True
            # Allow common '**/*.ext' style to match top-level files too
            if tok.startswith("**/"):
                tail = tok[3:]
                if PurePosixPath(rel_pp.name).match(tail):
                    return True
            return False
        except Exception:
            return False

    return any(matches_include(t) for t in includes)


def relpath_matches_filter(rel_posix: str, filter_str: str = "") -> bool:
    """
    Check if a repository-relative path (POSIX style, e.g., cloud object key) matches
    the rsync-like include/exclude rules. This avoids needing a real filesystem base.

    - rel_posix: path relative to a virtual base (e.g., 'sub1/file.txt'). Use forward slashes.
    - filter_str: DSXCONNECTOR_FILTER string.
    """
    # Normalize to posix path semantics
    rel = rel_posix.strip("/")
    pp = PurePosixPath(rel)

    includes, excludes, include_all, top_level_only = parse_filter_spec(filter_str)
    bare_ex_dirs, glob_ex_paths = _split_excludes(excludes)

    # Exclude checks
    if _is_excluded_rel(rel, glob_ex_paths):
        return False
    if bare_ex_dirs and any(part in bare_ex_dirs for part in pp.parts[:-1]):
        return False

    # Include-all cases
    if include_all:
        if top_level_only:
            return len(pp.parts) == 1
        return True

    def matches_include(tok: str) -> bool:
        if tok == "*":
            return len(pp.parts) == 1
        if tok.endswith("/*") and not _has_glob(tok[:-2]):
            parent = tok[:-2].strip("/")
            if not parent:
                return len(pp.parts) == 1
            return pp.parts[:-1] == PurePosixPath(parent).parts
        if not _has_glob(tok) and "/" not in tok:
            return rel == tok or rel.startswith(tok + "/")
        # General glob/path pattern
        if pp.match(tok):
            return True
        if tok.startswith("**/"):
            tail = tok[3:]
            if PurePosixPath(pp.name).match(tail):
                return True
        return False

    return any(matches_include(t) for t in includes)


def compute_prefix_hints(filter_str: str) -> List[str]:
    """
    Derive conservative provider-side prefix hints from the rsync-like filter.

    Returns a list of path prefixes (with trailing '/') that are safe to use as
    name_starts_with/prefix for cloud listings. Only produced when:
      - No excludes are present, and
      - Includes are bare paths or directory patterns (e.g., 'sub1', 'sub1/*', 'sub1/**').

    If any include uses glob characters beyond the trailing /* or /** pattern, or
    if excludes are present, returns an empty list to avoid under-fetching.
    """
    includes, excludes, include_all, top_level_only = parse_filter_spec(filter_str or "")
    if include_all or excludes:
        return []

    hints: list[str] = []
    for inc in includes:
        if inc in ("", "*"):
            return []
        if inc.endswith("/*") and not _has_glob(inc[:-2]):
            hints.append(inc[:-2].rstrip("/") + "/")
        elif inc.endswith("/**") and not _has_glob(inc[:-3]):
            hints.append(inc[:-3].rstrip("/") + "/")
        elif inc.endswith("/**/*") and not _has_glob(inc[:-4]):
            # Expanded rsync form; we've already covered the base subtree via the '/*' include
            # or we can still add the same hint safely.
            base = inc[:-4].rstrip("/")
            if base and base + "/" not in hints:
                hints.append(base + "/")
        elif not _has_glob(inc):
            hints.append(inc.rstrip("/") + "/")
        else:
            # Any other glob/path complexity → skip hints entirely to avoid under-fetching
            return []
    # Deduplicate while preserving order
    seen = set()
    out: list[str] = []
    for h in hints:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


# =======================
# Async path enumeration
# =======================

async def _estimate_file_count(base_dir: pathlib.Path, sample_limit: int = 500) -> int:
    """
    Quick estimate of file count to decide between sync vs async approach.
    Uses a sampling strategy to avoid traversing the entire tree.
    """
    try:
        count = 0
        dirs_checked = 0
        max_dirs_to_check = 10

        for root, dirs, files in os.walk(base_dir):
            count += len(files)
            dirs_checked += 1

            # Early exit if we find many files quickly
            if count > sample_limit:
                # Extrapolate based on directory depth and breadth
                depth_factor = max(1, dirs_checked)
                breadth_factor = max(1, len(dirs))
                return min(count * depth_factor * breadth_factor, 1_000_000)  # Cap estimation

            # Limit sampling to avoid long estimation times
            if dirs_checked >= max_dirs_to_check:
                break

        return count
    except Exception:
        return sample_limit + 1  # Default to async if estimation fails


async def get_filepaths_async(path: str | Path, filter_str: str = "") -> AsyncGenerator[Path, None]:
    """
    Optimized async generator yielding file paths with the same semantics as get_filepaths().
    Automatically chooses between sync and async approaches based on estimated dataset size.
    """
    root = Path(path).expanduser()
    if not root.exists():
        return

    if root.is_file():
        # For single files, just use sync approach
        for p in get_filepaths(root, filter_str):
            yield p
        return

    # Use the optimized rsync async version
    async for p in get_filepaths_rsync_async(root, filter_str):
        yield p


async def get_filepaths_rsync_async(
        base_dir: pathlib.Path,
        filter_str: str = "",
        batch_size: int = 200,
        small_dataset_threshold: int = 1000
) -> AsyncGenerator[pathlib.Path, None]:
    """
    Highly optimized async version of the full rsync-like file filtering.
    Uses hybrid sync/async approach and pathlib optimizations for best performance.
    """
    # Use the existing sophisticated filter parsing
    includes, excludes, include_all, top_level_only = parse_filter_spec(filter_str)

    dsx_logging.info(f"Parsed filter - includes: {includes}, excludes: {excludes}, include_all: {include_all}, top_level_only: {top_level_only}")

    # For small datasets, use sync version to avoid async overhead
    estimated_count = await _estimate_file_count(base_dir, small_dataset_threshold // 2)
    if estimated_count < small_dataset_threshold:
        # Use sync version for small datasets - it's faster
        for file_path in iter_files(base_dir, filter_str):
            yield file_path
        return

    # Convert to the internal format expected by the filtering functions
    include_tokens = list(includes) if not include_all else [""]
    bare_ex_dirs, glob_ex_paths = _split_excludes(excludes)

    # Track seen files to avoid duplicates
    seen = set()
    yielded_count = 0

    for inc in include_tokens:
        async for file_path in _process_include_token_async_optimized(
                inc, base_dir, top_level_only, bare_ex_dirs, glob_ex_paths, batch_size
        ):
            if file_path not in seen:
                seen.add(file_path)
                yield file_path
                yielded_count += 1

                # Yield control less frequently for better performance
                if yielded_count % batch_size == 0:
                    await asyncio.sleep(0.001)  # Shorter sleep


async def _process_include_token_async_optimized(
        inc: str,
        base: pathlib.Path,
        top_level_only: bool,
        bare_ex_dirs: tuple,
        glob_ex_paths: tuple,
        batch_size: int
) -> AsyncGenerator[pathlib.Path, None]:
    """
    Highly optimized async processing that maximizes pathlib usage and minimizes blocking.
    """

    # 1) Empty token → whole tree
    if inc == "":
        if top_level_only:
            for p in base.glob("*"):
                if p.is_file():
                    yield p
            return

        # For full tree, use optimized approach based on excludes
        if not glob_ex_paths and not bare_ex_dirs:
            # No excludes - use simple rglob (fastest path)
            count = 0
            for p in base.rglob("*"):
                if p.is_file():
                    yield p
                    count += 1
                    if count % batch_size == 0:
                        await asyncio.sleep(0.001)
            return

        # With excludes, use rglob but filter
        count = 0
        for p in base.rglob("*"):
            if not p.is_file():
                continue

            # Quick bare directory check
            if bare_ex_dirs and p.parent.name in bare_ex_dirs:
                continue

            # Glob path check (more expensive)
            if glob_ex_paths:
                rel = p.relative_to(base).as_posix()
                if _is_excluded_rel(rel, glob_ex_paths):
                    continue

            yield p
            count += 1
            if count % batch_size == 0:
                await asyncio.sleep(0.001)
        return

    # 2) Top-level only
    if inc == "*":
        for p in base.glob("*"):
            if p.is_file():
                yield p
        return

    # 3) Bare subtree - use pathlib when possible
    if not _has_glob(inc) and not inc.endswith("/*"):
        sub = base / inc

        if sub.is_file():
            # Quick exclude check for single file
            if bare_ex_dirs and sub.parent.name in bare_ex_dirs:
                return
            if glob_ex_paths:
                rel = sub.relative_to(base).as_posix()
                if _is_excluded_rel(rel, glob_ex_paths):
                    return
            yield sub
            return

        if not sub.is_dir():
            return

        # For subtree, optimize based on exclude patterns
        count = 0
        if not glob_ex_paths and not bare_ex_dirs:
            # No excludes - use simple rglob (fastest)
            for f in sub.rglob("*"):
                if f.is_file():
                    yield f
                    count += 1
                    if count % batch_size == 0:
                        await asyncio.sleep(0.001)
        else:
            # With excludes
            for f in sub.rglob("*"):
                if not f.is_file():
                    continue

                # Quick bare directory check
                if bare_ex_dirs and f.parent.name in bare_ex_dirs:
                    continue

                # Glob path check
                if glob_ex_paths:
                    rel = f.relative_to(base).as_posix()
                    if _is_excluded_rel(rel, glob_ex_paths):
                        continue

                yield f
                count += 1
                if count % batch_size == 0:
                    await asyncio.sleep(0.001)
        return

    # 4) Direct-children form 'sub1/*'
    if inc.endswith("/*") and not _has_glob(inc[:-2]):
        sub = base / inc[:-2]
        if sub.is_dir():
            for f in sub.glob("*"):
                if not f.is_file():
                    continue

                # Quick exclude checks
                if bare_ex_dirs and f.parent.name in bare_ex_dirs:
                    continue
                if glob_ex_paths:
                    rel = f.relative_to(base).as_posix()
                    if _is_excluded_rel(rel, glob_ex_paths):
                        continue

                yield f
        return

    # 5) Glob/path form - use rglob with optimizations
    count = 0
    for f in base.rglob(inc):
        if not f.is_file():
            continue
        if top_level_only and f.parent != base:
            continue

        # Quick exclude checks
        if bare_ex_dirs and f.parent.name in bare_ex_dirs:
            continue
        if glob_ex_paths:
            rel = f.relative_to(base).as_posix()
            if _is_excluded_rel(rel, glob_ex_paths):
                continue

        yield f
        count += 1
        if count % batch_size == 0:
            await asyncio.sleep(0.001)


# ============================
# Test and benchmark utilities
# ============================

if __name__ == "__main__":
    # Adjust base for your machine before running directly
    base = Path.home() / "Documents" / "SAMPLES"

    print("=== QUICK SANITY ===")
    tests = [
        # ("", "No filter → everything recursively"),
        ("*", "list top-level files only"),
        ("*.zip", "list all zip files anywhere"),
        ("PDF", "list files in PDF subtree and recurse into subtrees"),
        ("PDF/*", "list files in PDF subtree only"),
        ("PDF/sub1", "list files in PDF/sub1 subtree and recurse"),
        ("PDF -tmp", "'PDF' subtree and down, exclude tmp directories at any level"),
        ("PDF -tmp --exclude sub2", "'PDF' subtree and down, exclude tmp and sub2 subtrees at any level"),
        ("test/2025*/*", "list all files only at subtrees matching 'test/2025*/*' (ex: test/2025-01-15, test/2025-07-30, test/2025-08-12)"),
        ("test/2025*/** -sub2", "list all files within subtrees and down matching 'test/2025*/*' (ex: test/2025-01-15, test/2025-07-30, test/2025-07-30/sub1, test/2025-08-12)"),
        ("'test/scan here' -'not here' --exclude 'not here either'", "Quoted tokens (spaces in dir names)"),
    ]

    print("\n=== SYNC TEST ===")
    for filt, desc in tests:
        files = get_filepaths(base, filt)
        print(f"\nFilter: {filt!r}  ({desc})  -> {len(files)} files")
        for p in files[:10]:
            print("  .", p.relative_to(base))
        if len(files) > 5:
            print("  ...")

    print("\n=== ASYNC TEST ===")

    async def collect_async_files(async_generator, max_files: int = None) -> List[Path]:
        """Helper to collect files from async generator for testing"""
        files = []
        count = 0
        async for file_path in async_generator:
            files.append(file_path)
            count += 1
            if max_files and count >= max_files:
                break
        return files

    async def run_async_tests():
        for filt, desc in tests:
            async_generator = get_filepaths_rsync_async(base, filt, batch_size=100)
            files = await collect_async_files(async_generator, max_files=1000)  # Limit for testing

            print(f"\nFilter: {filt!r}  ({desc})  -> {len(files)} files")
            for p in files[:10]:
                print("  .", p.relative_to(base))
            if len(files) > 5:
                print("  ...")

    asyncio.run(run_async_tests())

    print("\n=== PERFORMANCE COMPARISON ===")

    async def compare_performance():
        comparison_filters = [
            ("*", "top-level only"),
            ("PDF", "PDF subtree"),
            ("*.zip", "all zip files"),
            ("0LOTS", "9662 files"),
            ("0LOTS1M", "1M"),
            ("..", "ALL"),
        ]

        for filt, desc in comparison_filters:
            print(f"\nComparing filter: {filt!r} ({desc})")

            # Test sync version
            try:
                start_time = time.time()
                sync_files = get_filepaths(base, filt)
                sync_time = time.time() - start_time
                print(f"  Sync:  {len(sync_files)} files in {sync_time:.3f}s")
            except Exception as e:
                print(f"  Sync:  ERROR - {e}")
                sync_files = []

            # Test async version
            try:
                start_time = time.time()
                async_gen = get_filepaths_rsync_async(base, filt, batch_size=200)
                async_files = await collect_async_files(async_gen)
                async_time = time.time() - start_time
                print(f"  Async: {len(async_files)} files in {async_time:.3f}s")

                # Compare results
                if len(sync_files) == len(async_files):
                    print(f"  ✅ Same number of files found")
                    if async_time < sync_time * 1.2:  # Allow 20% overhead for async
                        print(f"  🚀 Async performance: {sync_time/async_time:.1f}x (good)")
                    else:
                        print(f"  ⚠️  Async slower: {async_time/sync_time:.1f}x")
                else:
                    print(f"  ⚠️  Different counts: sync={len(sync_files)}, async={len(async_files)}")

            except Exception as e:
                print(f"  Async: ERROR - {e}")

    # Run performance comparison
    asyncio.run(compare_performance())
