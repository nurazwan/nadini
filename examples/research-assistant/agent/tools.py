"""Tools the agent can call. Add yours and append them to TOOLS."""

import ast
import operator
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from langchain_core.tools import tool

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "research-assistant-example/0.1 (nadini demo)"


@tool
def get_current_time(timezone: str = "UTC") -> str:
    """Return the current date and time in an IANA timezone, e.g. 'Asia/Kuala_Lumpur'."""
    try:
        now = datetime.now(ZoneInfo(timezone))
    except ZoneInfoNotFoundError:
        return f"Unknown timezone: {timezone}"
    return now.isoformat(timespec="seconds")


@tool
async def search_wikipedia(query: str, max_results: int = 3) -> list[dict]:
    """Search English Wikipedia. Returns title, url and a plain-text extract per page."""
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrlimit": max(1, min(max_results, 5)),
        "prop": "extracts|info",
        "exintro": 1,
        "explaintext": 1,
        "exchars": 1200,
        "inprop": "url",
    }
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": USER_AGENT}) as client:
        resp = await client.get(WIKIPEDIA_API, params=params)
        resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {}).values()
    return [
        {"title": p["title"], "url": p["fullurl"], "extract": p.get("extract", "")}
        for p in sorted(pages, key=lambda p: p.get("index", 0))
    ]


_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval(node: ast.AST) -> float:
    match node:
        case ast.Constant(value=int() | float() as value):
            return value
        case ast.BinOp(left=left, op=op, right=right) if type(op) in _OPS:
            if isinstance(op, ast.Pow) and abs(_eval(right)) > 100:
                raise ValueError("exponent too large")
            return _OPS[type(op)](_eval(left), _eval(right))
        case ast.UnaryOp(op=op, operand=operand) if type(op) in _OPS:
            return _OPS[type(op)](_eval(operand))
    raise ValueError(f"unsupported expression: {ast.dump(node)}")


@tool
def calculator(expression: str) -> str:
    """Evaluate an arithmetic expression exactly, e.g. '(1969 - 1903) * 12'.
    Supports + - * / // % ** and parentheses."""
    try:
        return str(_eval(ast.parse(expression, mode="eval").body))
    except (SyntaxError, ValueError, ZeroDivisionError) as exc:
        return f"Error: {exc}"


TOOLS = [search_wikipedia, calculator, get_current_time]
