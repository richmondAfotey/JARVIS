"""Small helper functions shared across JARVIS AI."""

from __future__ import annotations

import ast
import operator
import re
import time
from datetime import datetime

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}


def safe_eval_math(expression: str) -> str:
    """Evaluate a simple arithmetic expression without executing code.

    Uses Python's `ast` module to parse the input into a tree and only
    allows numbers and + - * / ** % operations. This is much safer than
    Python's built-in `eval()` because nothing arbitrary can run.
    """
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except (SyntaxError, ValueError):
        return ""

    def evaluate(node):
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            left = evaluate(node.left)
            right = evaluate(node.right)
            op = _BINOPS[type(node.op)]
            if isinstance(node.op, ast.Div) and right == 0:
                raise ZeroDivisionError
            return op(left, right)
        raise ValueError("unsupported expression")

    try:
        result = evaluate(tree)
    except (ZeroDivisionError, ValueError, TypeError, OverflowError):
        return ""

    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return str(result)


def now_str() -> str:
    """Current local date/time as a readable string."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def now_timestamp() -> int:
    """Current Unix timestamp (seconds since epoch)."""
    return int(time.time())


def clamp(value: float, low: float, high: float) -> float:
    """Keep `value` between `low` and `high`."""
    return max(low, min(high, value))


def sanitize_filename(name: str) -> str:
    """Remove characters that are not safe in filenames on Windows."""
    bad = '<>:"/\\|?*'
    cleaned = "".join("_" if ch in bad else ch for ch in name)
    return cleaned.strip() or "untitled"


def normalize_text(text: str) -> str:
    """Lowercase text, drop punctuation, collapse spaces.

    "Hey, JARVIS!"  ->  "hey jarvis"
    Used for lenient voice-phrase matching.
    """
    lowered = re.sub(r"[^a-z0-9\s']", " ", text.lower())
    return re.sub(r"\s+", " ", lowered).strip()
