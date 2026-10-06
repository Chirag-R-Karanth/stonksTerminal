from __future__ import annotations

from typing import Any

from app.ui import theme

NA = "—"


def iso_date(ts: Any) -> str:
    from datetime import datetime, timezone

    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return str(ts)


def num(value: Any, digits: int = 2) -> str:
    if value is None:
        return NA
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def int_num(value: Any) -> str:
    if value is None:
        return NA
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def compact(value: Any, digits: int = 2) -> str:
    if value is None:
        return NA
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    sign = "-" if v < 0 else ""
    v = abs(v)
    for limit, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if v >= limit:
            return f"{sign}{v / limit:.{digits}f}{suffix}"
    return f"{sign}{v:.{digits}f}"


def pct(value: Any, digits: int = 2, already_percent: bool = False) -> str:
    if value is None:
        return NA
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not already_percent:
        v *= 100.0
    return f"{v:+.{digits}f}%" if digits >= 0 else f"{v:.0f}%"


def pct_abs(value: Any, digits: int = 2, already_percent: bool = False) -> str:
    text = pct(0 if value is None else value, digits, already_percent)
    if value is None:
        return NA
    return text[1:] if text.startswith("+") else text


def money(value: Any, currency: str = "", digits: int = 2) -> str:
    if value is None:
        return NA
    text = num(value, digits)
    if currency in ("USD", ""):
        return f"${text}" if currency == "USD" else text
    return f"{text} {currency}"


def sign_class(value: Any, invert: bool = False) -> str:
    if value is None:
        return "ft-dim"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    if v == 0:
        return "ft-dim"
    up = v > 0
    if invert:
        up = not up
    return "ft-up" if up else "ft-down"


def color(value: Any, css_class: str) -> str:
    return css_class if value is not None else "ft-dim"


def short_time(iso: str | None) -> str:
    if not iso:
        return NA
    text = str(iso)
    if "T" in text:
        return text.split("T", 1)[1][:8]
    return text


def age(fetched_at: str | None) -> str:
    if not fetched_at:
        return NA
    from datetime import datetime, timezone

    try:
        ts = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
    except ValueError:
        return NA
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    seconds = (datetime.now(timezone.utc) - ts).total_seconds()
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


STATUS_LABELS = {
    "live": ("LIVE", "ft-up"),
    "cached": ("CACHED", "ft-dim"),
    "stale": ("STALE", "ft-warn"),
    "demo": ("DEMO DATA", "ft-warn"),
    "offline": ("OFFLINE", "ft-err"),
    "error": ("ERROR", "ft-err"),
}


def status_bits(status: str, provider: str = "", fetched_at: str | None = None) -> list[tuple[str, str]]:
    label, css = STATUS_LABELS.get(status, (status.upper(), "ft-dim"))
    bits = [(label, css)]
    if provider:
        bits.append((provider, "ft-dim"))
    if fetched_at:
        bits.append((age(fetched_at), "ft-dim"))
    return bits
