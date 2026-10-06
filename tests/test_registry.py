from app.commands.registry import (
    COMMANDS,
    SYMBOL_ACTIONS,
    help_lines,
    is_command,
    resolve_verb,
    spec_for,
)

CORE = {
    "HELP", "STATUS", "HISTORY", "CLEAR", "SETTINGS", "WATCHLIST", "PORTFOLIO",
    "SCREEN", "COMPARE", "NEWS", "MACRO", "MARKETS", "PROVENANCE", "FIND",
    "WORKSPACE", "REFRESH", "ALERTS", "CALENDAR", "NOTES", "BACKTEST", "EXPORT",
}


def test_core_commands_registered():
    assert CORE.issubset(set(COMMANDS))


def test_aliases_resolve():
    assert resolve_verb("wl") == "WATCHLIST"
    assert resolve_verb("POS") == "PORTFOLIO"
    assert resolve_verb("port") == "PORTFOLIO"
    assert is_command("mkt") or is_command("MARKETS")
    assert not is_command("AAPL")


def test_specs_have_usage():
    for name, spec in COMMANDS.items():
        assert spec.name == name
        assert spec.usage
        assert spec.help


def test_help_topics():
    general = help_lines()
    assert general and any("HELP" in line for line in general)
    filters = help_lines("FILTERS")
    assert any("PE" in line for line in filters)
    unknown = help_lines("NOT_A_TOPIC")
    assert unknown and "unknown help topic" in unknown[0]


def test_symbol_actions_documented():
    for action in ("CHART", "FIN", "VAL", "NEWS", "PEERS", "EARNINGS", "RISK"):
        assert action in SYMBOL_ACTIONS


def test_spec_for_alias_free_names():
    assert spec_for("SCREEN") is not None
    assert spec_for("NOPE") is None
