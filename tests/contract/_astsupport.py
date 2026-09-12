"""Static-analysis helpers for the cross-package contract tests. ★ Imports nothing heavy.

**Why `ast` and not `import`.** The properties these tests assert are *structural*: three
enum files must agree; `ai_engine` must contain no CRS vocabulary; `gis` must contain no
descriptor vocabulary. None of that needs the modules to be importable — and that is the
whole point, because on this machine they are **not**. `backend.app.models.enums` needs
sqlalchemy and `backend.app.schemas.enums` needs pydantic, neither of which is installed
(§0.1). An import-based parity test cannot run here at all; an `ast`-based one runs today,
on a bare interpreter, with zero installs.

That is not a workaround. A test that only runs in a fully provisioned container is a test
that runs late — and enum drift between three hand-maintained files is exactly the defect
you want caught on the first commit, not in CI an hour later.

★ **This module is deliberately free of `pytest`** so its logic can be exercised by a plain
interpreter as well as by the suite.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

_ENUM_BASES: Final[frozenset[str]] = frozenset({"StrEnum", "Enum", "IntEnum"})


# =============================================================================
# Enum extraction
# =============================================================================


def _is_enum_class(node: ast.ClassDef) -> bool:
    """True if the class derives from an enum base, by NAME.

    Name-based because the file is never imported: `enum.StrEnum` and a bare `StrEnum`
    both count, and nothing else does.
    """
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id in _ENUM_BASES:
            return True
        if isinstance(base, ast.Attribute) and base.attr in _ENUM_BASES:
            return True
    return False


def enum_members(path: Path) -> dict[str, dict[str, str]]:
    """Extract ``{ClassName: {MEMBER_NAME: value}}`` for every string-enum in a file.

    Only members assigned a plain string literal are returned — an enum member whose value
    is computed is not a wire value and cannot be in parity with a PG label.

    Args:
        path: The ``.py`` file to parse. It is never imported.

    Returns:
        A mapping of enum class name to its ``{member: value}`` mapping, in source order.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: dict[str, dict[str, str]] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or not _is_enum_class(node):
            continue
        members: dict[str, str] = {}
        for stmt in node.body:
            target: str | None = None
            value: ast.expr | None = None
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                if isinstance(stmt.targets[0], ast.Name):
                    target = stmt.targets[0].id
                    value = stmt.value
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                target = stmt.target.id
                value = stmt.value
            if target is None or value is None or target.startswith("_"):
                continue
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                members[target] = value.value
        if members:
            found[node.name] = members

    return found


# =============================================================================
# Code-only text (the §10.5 gates, done correctly)
# =============================================================================


def code_lines(path: Path) -> dict[int, str]:
    """Return ``{lineno: code_text}`` for a file, with comments AND docstrings removed.

    ★ **This is what §10.5's `strip_comments` is trying to be.** §10.5 rule 1 is explicit
    about the intent — *"Code, not prose"* — and explains why: §4.10's mandated `windows.py`
    carries ``crs: str  # OPAQUE. e.g. "EPSG:3857"``, and a naive L3 grep goes red on the
    very comment that explains the boundary it enforces.

    The shell it prescribes does not quite achieve that intent, because it greps *first* and
    strips *after*::

        py_src -iE 'epsg|…' ai_engine/src/ai_engine/ | strip_comments

    `grep -rn` emits ``path:lineno:text``. `strip_comments`'s ``/^[[:space:]]*#/d`` deletes
    lines *beginning* with ``#`` — but every line it sees begins with ``path:``, so that rule
    can never fire. A whole-line comment containing ``EPSG`` is matched by grep, survives the
    delete, and its trailing-comment substitution leaves the non-empty stub ``path:12:``.
    The gate then fails on prose anyway. Stripping before matching — which parsing does for
    free, since comments are not in the AST — is the only way to get the stated behaviour.

    The token *vocabulary* below is taken verbatim from §10.5 and is not reinvented.

    Args:
        path: The ``.py`` file to read.

    Returns:
        ``{lineno: text}``. Tokens are space-joined, so a pattern spanning tokens (``L3b``'s
        ``geotransform\\s*\\[``) still matches, while a comment cannot.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    docstring_lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
            and first.value.end_lineno is not None
        ):
            docstring_lines.update(range(first.value.lineno, first.value.end_lineno + 1))

    skip = {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENDMARKER,
        tokenize.ENCODING,
    }
    per_line: dict[int, list[str]] = {}
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in skip:
            continue
        if token.type == tokenize.STRING and token.start[0] in docstring_lines:
            continue
        per_line.setdefault(token.start[0], []).append(token.string)

    return {lineno: " ".join(parts) for lineno, parts in per_line.items()}


def source_files(package_dir: Path) -> list[Path]:
    """Every ``.py`` file under ``package_dir``, excluding ``tests`` directories.

    ★ §10.5 rule 2, *"Source, not tests"*: §2.2 puts `tests/` **inside** the package, and
    IU-03's mandated test *"nothing imports `cv2.xfeatures2d`"* must contain that literal
    string in order to assert on it — so a repo-wide gate fails on the very test that proves
    the property. `--exclude-dir=tests` throughout.
    """
    return sorted(
        path
        for path in package_dir.rglob("*.py")
        if "tests" not in path.relative_to(package_dir).parts
    )


def scan(package_dir: Path, pattern: str, *, flags: int = re.IGNORECASE) -> list[str]:
    """Return ``path:lineno: text`` for every CODE line matching ``pattern``.

    Args:
        package_dir: Root of the package subtree to scan.
        pattern: A §10.5 regex. Not invented here — copied from the contract.
        flags: Regex flags. §10.5's L3/L4 gates are ``-i``; L3b is not.

    Returns:
        Human-readable hits, empty when the gate passes.
    """
    regex = re.compile(pattern, flags)
    hits: list[str] = []
    for path in source_files(package_dir):
        for lineno, text in sorted(code_lines(path).items()):
            if regex.search(text):
                rel = path.relative_to(REPO_ROOT)
                hits.append(f"{rel}:{lineno}: {text.strip()}")
    return hits
