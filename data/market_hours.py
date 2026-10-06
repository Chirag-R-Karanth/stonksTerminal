from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from app.config import Config

STATUS_OPEN = "OPEN"
STATUS_CLOSED = "CLOSED"
STATUS_PRE = "PRE-MARKET"
STATUS_POST = "AFTER-HOURS"
STATUS_WEEKEND = "WEEKEND"

TERMINAL_TIME_FORMAT = "%H:%M:%S"


@dataclass(frozen=True)
class Session:
    exchange: str
    timezone: str
    open: str
    close: str
    pre_open: str
    post_close: str
    holidays: tuple[str, ...] = ()

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def _time(self, value: str) -> time:
        hour, minute = value.split(":")
        return time(int(hour), int(minute))


def load_sessions(config: Config) -> list[Session]:
    sessions: list[Session] = []
    for name, raw in config.section("session").items():
        if not isinstance(raw, dict):
            continue
        sessions.append(
            Session(
                exchange=str(raw.get("exchange", name)),
                timezone=str(raw.get("timezone", "UTC")),
                open=str(raw.get("open", "09:30")),
                close=str(raw.get("close", "16:00")),
                pre_open=str(raw.get("pre_open", "04:00")),
                post_close=str(raw.get("post_close", "20:00")),
                holidays=tuple(raw.get("holidays", ()) or ()),
            )
        )
    return sorted(sessions, key=lambda s: s.exchange)


def session_status(session: Session, now: datetime | None = None) -> str:
    local = (now or datetime.now(timezone.utc)).astimezone(session.tz)
    if local.weekday() >= 5:
        return STATUS_WEEKEND
    if local.strftime("%Y-%m-%d") in session.holidays:
        return STATUS_CLOSED
    current = local.time()
    if session._time(session.open) <= current < session._time(session.close):
        return STATUS_OPEN
    if session._time(session.pre_open) <= current < session._time(session.open):
        return STATUS_PRE
    if session._time(session.close) <= current < session._time(session.post_close):
        return STATUS_POST
    return STATUS_CLOSED


def local_clock(session: Session, now: datetime | None = None) -> str:
    local = (now or datetime.now(timezone.utc)).astimezone(session.tz)
    return local.strftime(TERMINAL_TIME_FORMAT)


NSE_SYMBOLS = {"NIFTY", "NIFTYBANK", "BANKNIFTY", "^NSEI"}
BSE_SYMBOLS = {"SENSEX", "^BSESN"}


def exchange_for_symbol(symbol: str) -> str:
    upper = symbol.upper()
    if upper.endswith(".NS") or upper in NSE_SYMBOLS:
        return "NSE"
    if upper.endswith(".BO") or upper in BSE_SYMBOLS:
        return "BSE"
    return "NYSE"


def symbol_session_status(symbol: str, sessions: list[Session], now: datetime | None = None) -> str:
    wanted = exchange_for_symbol(symbol)
    for session in sessions:
        if session.exchange == wanted:
            return session_status(session, now)
    return "UNKNOWN"
