from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING, Any, Callable

from app.commands.outcome import CommandOutcome, error, message, panel
from app.commands.parser import Command, Filter
from app.commands.registry import SYMBOL_ACTIONS, help_lines, spec_for

if TYPE_CHECKING:
    from app.state.app_state import AppState

log = logging.getLogger(__name__)

Handler = Callable[["AppState", Command], CommandOutcome]

PERIOD_SET = {"INTRA", "1D", "5D", "1M", "3M", "6M", "1Y", "2Y", "5Y", "MAX"}


def _float(raw: str) -> float:
    return float(raw.replace(",", ""))


def _date_or_today(raw: str | None) -> str:
    if not raw or raw.upper() == "TODAY":
        return date.today().isoformat()
    return date.fromisoformat(raw).isoformat()


def _coerce(raw: str) -> Any:
    lowered = raw.lower()
    if lowered in ("true", "yes", "on"):
        return True
    if lowered in ("false", "no", "off"):
        return False
    if lowered in ("null", "none"):
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def handle_symbol(state: "AppState", cmd: Command) -> CommandOutcome:
    action = cmd.action
    if action == "NEWS":
        return panel("news", symbols=[cmd.symbol], query=None)
    if action == "PEERS":
        peers = state.security.peers(cmd.symbol)
        symbols = [cmd.symbol] + [p.upper() for p in peers if p.upper() != cmd.symbol]
        if len(symbols) == 1:
            return message(f"no peers configured for {cmd.symbol}", level="warn")
        return panel("compare", symbols=symbols)
    if action == "PROVENANCE":
        return _provenance_for(state, cmd.symbol)
    tab = {
        "": "overview",
        "CHART": "chart",
        "FIN": "fin",
        "VAL": "val",
        "EARNINGS": "earnings",
        "OVERVIEW": "overview",
        "RISK": "risk",
    }.get(action, action.lower())
    period = ""
    if cmd.args and cmd.args[0].upper() in PERIOD_SET:
        period = cmd.args[0].upper()
    return panel("security", symbol=cmd.symbol, action=tab, period=period)


def _help(state: "AppState", cmd: Command) -> CommandOutcome:
    topic = " ".join(cmd.args).strip() or None
    return panel("help", topic=topic, lines=help_lines(topic))


def _history(state: "AppState", cmd: Command) -> CommandOutcome:
    limit = 50
    if cmd.args:
        try:
            limit = max(1, min(int(cmd.args[0]), 500))
        except ValueError:
            return error("usage: HISTORY [N]")
    rows = state.history.recent(limit)
    if not rows:
        return message("(command history is empty)")
    return message("\n".join(f"{i + 1:>3}. {row}" for i, row in enumerate(rows)))


def _clear(state: "AppState", cmd: Command) -> CommandOutcome:
    return CommandOutcome(ok=True, kind="clear")


def _settings(state: "AppState", cmd: Command) -> CommandOutcome:
    config = state.config
    if not cmd.args:
        rows = sorted(config.all().items()) if hasattr(config, "all") else []
        if not rows:
            return message("(no settings)")
        return message("\n".join(f"{key} = {value}" for key, value in rows))
    sub = cmd.args[0].upper()
    if sub == "GET" and len(cmd.args) >= 2:
        key = cmd.args[1]
        value = config.get(key, "<unset>")
        return message(f"{key} = {value}")
    if sub == "SET" and len(cmd.args) >= 3:
        key = cmd.args[1]
        value = _coerce(" ".join(cmd.args[2:]))
        config.set(key, value)
        return message(f"{key} = {value}")
    if sub == "RESET" and len(cmd.args) >= 2:
        key = cmd.args[1]
        config.delete(key)
        return message(f"{key} reset to default ({config.get(key)})")
    return error("usage: SETTINGS [GET KEY|SET KEY VALUE|RESET KEY]")


def _watchlist(state: "AppState", cmd: Command) -> CommandOutcome:
    svc = state.watchlists
    if not cmd.args:
        name = svc.ensure()
        return panel("watchlist", list=name)
    sub = cmd.args[0].upper()
    args = cmd.args[1:]
    if sub == "CREATE":
        if not args:
            return error("usage: WATCHLIST CREATE NAME")
        if svc.create(args[0]):
            return message(f"created watchlist {args[0]}")
        return error(f"watchlist {args[0]} already exists")
    if sub == "DELETE":
        if not args:
            return error("usage: WATCHLIST DELETE NAME")
        if svc.delete(args[0]):
            return message(f"deleted watchlist {args[0]}")
        return error(f"unknown watchlist {args[0]}")
    if sub in ("USE", "SHOW"):
        if not args:
            return error("usage: WATCHLIST USE NAME")
        if not svc.set_active(args[0]):
            return error(f"unknown watchlist {args[0]}")
        return panel("watchlist", list=args[0])
    if sub in ("ADD", "REMOVE"):
        if not args:
            return error(f"usage: WATCHLIST {sub} SYMBOL [LIST]")
        names = [n.lower() for n in svc.names()]
        target = svc.ensure()
        symbols = list(args)
        if len(args) >= 2 and args[-1].lower() in names:
            target = args[-1]
            symbols = args[:-1]
        results = []
        for symbol in symbols:
            if sub == "ADD":
                try:
                    svc.add(target, symbol)
                    results.append(f"+{symbol.upper()}")
                except Exception as exc:
                    results.append(f"{symbol.upper()}: {exc}")
            else:
                results.append(f"-{symbol.upper()}" if svc.remove(target, symbol) else f"{symbol.upper()}: not found")
        return message(f"{target}: {', '.join(results)}")
    if cmd.args and cmd.args[0].lower() in [n.lower() for n in svc.names()]:
        if not svc.set_active(cmd.args[0]):
            return error(f"unknown watchlist {cmd.args[0]!r}")
        return panel("watchlist", list=cmd.args[0])
    return error(f"unknown watchlist subcommand {sub!r}")


def _portfolio(state: "AppState", cmd: Command) -> CommandOutcome:
    svc = state.portfolio
    if not cmd.args:
        return panel("portfolio", tab="holdings")
    sub = cmd.args[0].upper()
    args = cmd.args[1:]
    if sub in ("ADD", "BUY", "SELL"):
        if len(args) < 3:
            return error(f"usage: PORTFOLIO {sub} SYMBOL QTY PRICE [DATE]")
        side = "SELL" if sub == "SELL" else "BUY"
        try:
            qty = _float(args[1])
            price = _float(args[2])
            when = _date_or_today(args[3] if len(args) > 3 else None)
            tx_id = svc.add(side, args[0], qty, price, when)
        except (ValueError, KeyError) as exc:
            return error(f"invalid transaction: {exc}")
        verb = "sold" if side == "SELL" else "bought"
        return message(f"{verb} {qty:g} {args[0].upper()} @ {price:g} on {when} (tx #{tx_id})")
    if sub in ("DIV", "DIVIDEND"):
        if len(args) < 2:
            return error("usage: PORTFOLIO DIV SYMBOL AMOUNT [DATE]")
        try:
            amount = _float(args[1])
            when = _date_or_today(args[2] if len(args) > 2 else None)
            tx_id = svc.add("DIVIDEND", args[0], 1.0, amount, when)
        except (ValueError, KeyError) as exc:
            return error(f"invalid dividend: {exc}")
        return message(f"dividend {amount:g} for {args[0].upper()} on {when} (tx #{tx_id})")
    if sub in ("DEPOSIT", "WITHDRAWAL"):
        if not args:
            return error(f"usage: PORTFOLIO {sub} AMOUNT [DATE]")
        try:
            amount = _float(args[0])
            when = _date_or_today(args[1] if len(args) > 1 else None)
            tx_id = svc.add(sub, "CASH", 1.0, amount, when)
        except (ValueError, KeyError) as exc:
            return error(f"invalid cash flow: {exc}")
        return message(f"{sub.lower()} {amount:g} on {when} (tx #{tx_id})")
    if sub == "BENCHMARK":
        if not args:
            return error("usage: PORTFOLIO BENCHMARK SYMBOL")
        try:
            state.market.resolve(args[0])
        except Exception as exc:
            return error(str(exc))
        svc.set_benchmark(args[0])
        return message(f"benchmark set to {args[0].upper()}")
    if sub == "RISK":
        return panel("portfolio", tab="risk")
    if sub in ("PERFORMANCE", "PERF"):
        period = "1Y"
        if args:
            if args[0].upper() not in PERIOD_SET:
                return error(f"period must be one of {', '.join(sorted(PERIOD_SET))}")
            period = args[0].upper()
        return panel("portfolio", tab="performance", period=period)
    if sub == "HISTORY":
        return panel("portfolio", tab="history")
    if sub == "DELETE":
        if not args:
            return error("usage: PORTFOLIO DELETE TRANSACTION_ID")
        try:
            tx_id = int(args[0])
        except ValueError:
            return error("transaction id must be a number")
        if svc.delete_transaction(tx_id):
            return message(f"deleted transaction #{tx_id}")
        return error(f"no transaction #{tx_id}")
    if sub == "HOLDINGS":
        return panel("portfolio", tab="holdings")
    spec = spec_for("PORTFOLIO")
    return error(spec.usage if spec else "unknown portfolio subcommand")


def _news(state: "AppState", cmd: Command) -> CommandOutcome:
    query = " ".join(cmd.args).strip() or None
    return panel("news", query=query, symbols=None)


def _macro(state: "AppState", cmd: Command) -> CommandOutcome:
    if not cmd.args:
        return panel("macro", series=None)
    key = cmd.args[0].upper()
    known = {c["key"] for c in state.macro.catalog()}
    if key in known:
        return panel("macro", series=key)
    for entry in state.macro.catalog():
        if entry["series"].upper() == key:
            return panel("macro", series=entry["key"])
    return error(f"unknown series {cmd.args[0]!r}; try: {', '.join(sorted(known))}")


def _screen(state: "AppState", cmd: Command) -> CommandOutcome:
    words = [w.upper() for w in cmd.args]
    if not words:
        if cmd.filters:
            filters_text = " ".join(f.text() for f in cmd.filters)
            return panel("screener", filters=filters_text, autorun=True)
        return panel("screener", filters="", autorun=False)
    sub = words[0]
    if sub == "SAVE":
        if len(words) < 2 or not cmd.filters:
            return error("usage: SCREEN SAVE NAME FIELD<VALUE ...")
        name = cmd.args[1]
        filters_text = " ".join(f.text() for f in cmd.filters)
        state.screener.save(name, filters_text)
        return message(f"saved screen {name.upper()}: {filters_text}")
    if sub == "LOAD":
        if len(words) < 2:
            return error("usage: SCREEN LOAD NAME")
        text = state.screener.load(cmd.args[1])
        if text is None:
            return error(f"unknown screen {cmd.args[1]!r}")
        return panel("screener", filters=text, autorun=True)
    if sub == "LIST":
        rows = state.screener.list()
        if not rows:
            return message("(no saved screens)")
        return message(
            "\n".join(f"{row['name']:<16} {row['query']}" for row in rows)
        )
    if sub == "DELETE":
        if len(words) < 2:
            return error("usage: SCREEN DELETE NAME")
        if state.screener.delete(cmd.args[1]):
            return message(f"deleted screen {words[1]}")
        return error(f"unknown screen {cmd.args[1]!r}")
    return error(f"unknown SCREEN subcommand {cmd.args[0]!r}")


def _screener(state: "AppState", cmd: Command) -> CommandOutcome:
    return panel("screener", filters="", autorun=False)


def _compare(state: "AppState", cmd: Command) -> CommandOutcome:
    symbols = [a.upper() for a in cmd.args]
    if len(symbols) < 2:
        return error("usage: COMPARE SYMBOL SYMBOL [SYMBOL...]")
    return panel("compare", symbols=symbols)


def _markets(state: "AppState", cmd: Command) -> CommandOutcome:
    return panel("markets")


def _status(state: "AppState", cmd: Command) -> CommandOutcome:
    info = state.status_summary()
    providers = info["providers"]
    lines = [
        f"providers    : market={providers['market']} fundamentals={providers['fundamentals']} "
        f"news={providers['news']} macro={providers['macro']}",
        f"mode         : {'DEMO (synthetic, labeled)' if info['demo_mode'] else 'live data'}"
        f" / {'OFFLINE' if info['offline'] else 'online'}",
        f"R analytics  : {'available' if info['r_available'] else 'UNAVAILABLE (graceful degradation)'}",
        f"database     : {info['db_path']}",
        f"data dir     : {info['data_dir']}",
        f"cache ttl    : quote={info['quote_ttl']:.0f}s news={info['news_ttl']:.0f}s",
        f"watchlists   : {', '.join(info['watchlists'])}",
        f"screening n  : {info['universe_size']} symbols in universe",
    ]
    return message("\n".join(lines))


def _refresh(state: "AppState", cmd: Command) -> CommandOutcome:
    return CommandOutcome(ok=True, kind="refresh")


def _workspace(state: "AppState", cmd: Command) -> CommandOutcome:
    layouts_raw = state.settings.get("workspace.layouts", {}) or {}
    layouts: dict[str, Any] = dict(layouts_raw)
    active = str(state.settings.get("workspace.active", "default"))
    if not cmd.args:
        names = ", ".join(sorted(layouts)) or "(none)"
        return message(f"workspaces: {names} (active: {active})")
    sub = cmd.args[0].upper()
    if sub == "NEW":
        if len(cmd.args) < 2:
            return error("usage: WORKSPACE NEW NAME")
        name = cmd.args[1]
        layouts.setdefault(name, {})
        state.settings.set("workspace.layouts", layouts)
        state.settings.set("workspace.active", name)
        return message(f"workspace {name} created and active")
    if sub == "USE":
        if len(cmd.args) < 2:
            return error("usage: WORKSPACE USE NAME")
        name = cmd.args[1]
        if name not in layouts:
            layouts[name] = {}
            state.settings.set("workspace.layouts", layouts)
        state.settings.set("workspace.active", name)
        state.notify("workspace", {"name": name, "layout": layouts.get(name) or {}})
        return message(f"workspace {name} active")
    if sub == "SAVE":
        current = state.current_view_fn() if state.current_view_fn else None
        if current is None:
            return error("no current view to save (UI not ready)")
        layouts[active] = current
        state.settings.set("workspace.layouts", layouts)
        return message(f"saved view {current.get('view')} to workspace {active}")
    return error("usage: WORKSPACE [NEW NAME|USE NAME|SAVE]")


def _provenance_for(state: "AppState", entity: str) -> CommandOutcome:
    lines: list[str] = []
    for data_type in ("quote", "history", "fundamentals", "statements"):
        row = state.provenance.latest(entity, data_type)
        if row:
            lines.append(
                f"{data_type:<13} {row.get('provider', ''):<12} {row.get('source', ''):<28} "
                f"{row.get('retrieved_at', '')}"
            )
    if not lines:
        return message(f"no provenance recorded for {entity}")
    return message(f"provenance for {entity}:\n" + "\n".join(lines))


def _provenance(state: "AppState", cmd: Command) -> CommandOutcome:
    if cmd.args:
        return _provenance_for(state, cmd.args[0].upper())
    rows = state.db.query(
        "SELECT entity, data_type, provider, source, retrieved_at FROM provenance "
        "ORDER BY id DESC LIMIT 15"
    )
    if not rows:
        return message("no provenance recorded yet")
    return message(
        "\n".join(
            f"{r['entity']:<14} {r['data_type']:<13} {r['provider']:<12} {r['retrieved_at']}"
            for r in rows
        )
    )


def _find(state: "AppState", cmd: Command) -> CommandOutcome:
    if not cmd.args:
        return error("usage: FIND QUERY")
    query = " ".join(cmd.args)
    results = state.market.search(query, limit=8)
    if not results:
        return message(f"no symbols matched {query!r}")
    return message(
        "\n".join(
            f"{info.symbol:<14} {info.name[:40]:<40} {info.exchange} {info.quote_type}"
            for info in results
        )
    )


def _planned(state: "AppState", cmd: Command) -> CommandOutcome:
    spec = spec_for(cmd.verb)
    name = spec.name if spec else cmd.verb
    return message(f"{name} is planned for a later phase — not implemented yet", level="warn")


HANDLERS: dict[str, Handler] = {
    "HELP": _help,
    "HISTORY": _history,
    "CLEAR": _clear,
    "SETTINGS": _settings,
    "WATCHLIST": _watchlist,
    "PORTFOLIO": _portfolio,
    "NEWS": _news,
    "MACRO": _macro,
    "SCREEN": _screen,
    "SCREENER": _screener,
    "COMPARE": _compare,
    "MARKETS": _markets,
    "STATUS": _status,
    "REFRESH": _refresh,
    "WORKSPACE": _workspace,
    "PROVENANCE": _provenance,
    "FIND": _find,
    "ALERTS": _planned,
    "CALENDAR": _planned,
    "NOTES": _planned,
    "BACKTEST": _planned,
    "EXPORT": _planned,
}


def dispatch(state: "AppState", cmd: Command) -> CommandOutcome:
    handler = HANDLERS.get(cmd.verb)
    if handler is None:
        return error(f"no handler for {cmd.verb}")
    return handler(state, cmd)
