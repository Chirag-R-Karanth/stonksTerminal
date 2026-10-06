from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CommandSpec:
    name: str
    usage: str
    help: str
    aliases: tuple[str, ...] = ()
    planned: bool = False


COMMANDS: dict[str, CommandSpec] = {}


def _register(spec: CommandSpec) -> None:
    COMMANDS[spec.name] = spec


_register(CommandSpec("HELP", "HELP [TOPIC]", "show command help; topics: SYMBOLS, FILTERS, PORTFOLIO, WATCHLIST, SCREEN"))
_register(CommandSpec("FIND", "FIND QUERY", "search for symbols by name", aliases=("SEARCH",)))
_register(CommandSpec("MARKETS", "MARKETS", "market overview: indices, rates, movers", aliases=("MKT", "OVERVIEW")))
_register(CommandSpec("NEWS", "NEWS [QUERY]", "news headlines, optionally filtered"))
_register(CommandSpec("WATCHLIST", "WATCHLIST [LIST|ADD SYM|REMOVE SYM|CREATE NAME|DELETE NAME|USE NAME]", "manage watchlists", aliases=("WL",)))
_register(CommandSpec("PORTFOLIO", "PORTFOLIO [ADD SYM QTY PRICE [DATE]|SELL SYM QTY PRICE [DATE]|DIV SYM AMT|BENCHMARK SYM|RISK|PERFORMANCE [PERIOD]|HISTORY|DELETE ID]", "manage portfolio", aliases=("POS", "PORT")))
_register(CommandSpec("SCREEN", "SCREEN [FILTERS...|SAVE NAME FILTERS|LOAD NAME|LIST|DELETE NAME]", "run or manage saved screens", aliases=("SCR",)))
_register(CommandSpec("SCREENER", "SCREENER", "open the interactive screener view"))
_register(CommandSpec("COMPARE", "COMPARE SYM SYM [SYM...]", "compare several securities"))
_register(CommandSpec("MACRO", "MACRO [SERIES]", "macroeconomic series and yield curve"))
_register(CommandSpec("SETTINGS", "SETTINGS [GET KEY|SET KEY VALUE|RESET KEY]", "view or change settings"))
_register(CommandSpec("HISTORY", "HISTORY [N]", "show recent commands", aliases=("HIST",)))
_register(CommandSpec("CLEAR", "CLEAR", "clear the console log", aliases=("CLS",)))
_register(CommandSpec("STATUS", "STATUS", "providers, cache, and system status"))
_register(CommandSpec("REFRESH", "REFRESH", "re-fetch data for the current view", aliases=("UPDATE",)))
_register(CommandSpec("WORKSPACE", "WORKSPACE [NEW NAME|USE NAME|SAVE]", "save and switch workspace layouts", aliases=("WS",)))
_register(CommandSpec("PROVENANCE", "PROVENANCE [SYMBOL]", "data provenance for fetched entities"))
_register(CommandSpec("ALERTS", "ALERTS", "price and data alerts", planned=True))
_register(CommandSpec("CALENDAR", "CALENDAR", "earnings and economic calendar", planned=True))
_register(CommandSpec("NOTES", "NOTES SYMBOL TEXT", "attach notes to symbols", planned=True))
_register(CommandSpec("BACKTEST", "BACKTEST STRATEGY", "rule-based backtesting", planned=True))
_register(CommandSpec("EXPORT", "EXPORT VIEW", "export view data to CSV", planned=True))

ALIASES: dict[str, str] = {}
for _spec in COMMANDS.values():
    for _alias in _spec.aliases:
        ALIASES[_alias] = _spec.name

SYMBOL_ACTIONS: dict[str, str] = {
    "CHART": "price chart with indicators",
    "FIN": "fundamentals and financial statements",
    "VAL": "valuation ratios and model",
    "NEWS": "news for this symbol",
    "PEERS": "peer comparison",
    "EARNINGS": "earnings and key events",
    "OVERVIEW": "security overview",
    "RISK": "risk metrics for this symbol",
    "PROVENANCE": "data provenance for this symbol",
}

PERIODS: tuple[str, ...] = ("INTRA", "1D", "5D", "1M", "3M", "6M", "1Y", "2Y", "5Y", "MAX")


def resolve_verb(word: str) -> str:
    upper = word.upper()
    return ALIASES.get(upper, upper)


def is_command(word: str) -> bool:
    upper = word.upper()
    return upper in COMMANDS or upper in ALIASES


def spec_for(verb: str) -> CommandSpec | None:
    return COMMANDS.get(verb)


def command_names() -> list[str]:
    return sorted(COMMANDS)


def help_lines(topic: str | None = None) -> list[str]:
    if topic:
        wanted = topic.upper()
        if wanted in ("SYMBOLS", "SYMBOL", "SECURITY"):
            lines = ["SYMBOL COMMANDS (type a symbol first):", ""]
            for action, description in SYMBOL_ACTIONS.items():
                lines.append(f"  SYMBOL {action:<10} {description}")
            lines.append("")
            lines.append("periods for CHART: " + ", ".join(PERIODS))
            return lines
        if wanted in ("FILTERS", "FILTER", "SCREEN"):
            from app.services.screener_service import filter_help

            fields = filter_help()
            lines = ["SCREEN FILTER FIELDS (e.g. SCREEN PE<20 ROE>0.15 MARKETCAP>2e10):", ""]
            for i in range(0, len(fields), 6):
                lines.append("  " + "  ".join(f"{f:<14}" for f in fields[i:i + 6]))
            lines.append("")
            lines.append("operators: < <= > >= == != ; percent fields accept % (ROE>15%)")
            return lines
        if wanted in ("PORTFOLIO", "POS"):
            spec = COMMANDS["PORTFOLIO"]
            return [f"usage: {spec.usage}", "", spec.help]
        if wanted in ("WATCHLIST", "WL"):
            spec = COMMANDS["WATCHLIST"]
            return [f"usage: {spec.usage}", "", spec.help]
        spec = COMMANDS.get(wanted)
        if spec:
            return [f"usage: {spec.usage}", "", spec.help]
        return [f"unknown help topic {topic!r}; try: SYMBOLS, FILTERS, PORTFOLIO, WATCHLIST"]
    lines = ["COMMANDS (type a symbol such as AAPL for security views):", ""]
    for spec in COMMANDS.values():
        mark = " (planned)" if spec.planned else ""
        lines.append(f"  {spec.name:<11} {spec.help}{mark}")
    lines.append("")
    lines.append("HELP SYMBOLS | HELP FILTERS | HELP PORTFOLIO | HELP WATCHLIST")
    return lines
