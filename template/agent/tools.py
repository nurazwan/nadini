"""Tools the agent can call. Add yours and append them to TOOLS."""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.tools import tool


@tool
def get_current_time(timezone: str = "UTC") -> str:
    """Return the current date and time in an IANA timezone, e.g. 'Asia/Kuala_Lumpur'."""
    try:
        now = datetime.now(ZoneInfo(timezone))
    except ZoneInfoNotFoundError:
        return f"Unknown timezone: {timezone}"
    return now.isoformat(timespec="seconds")


TOOLS = [get_current_time]
