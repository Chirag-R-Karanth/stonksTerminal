from app.commands.engine import CommandEngine


def test_help_panel(demo_state):
    out = CommandEngine(demo_state).execute("HELP")
    assert out.ok
    assert out.kind == "panel"
    assert out.panel["view"] == "help"
    assert out.panel["topic"] is None
    assert out.panel["lines"]


def test_help_topic(demo_state):
    out = CommandEngine(demo_state).execute("HELP FILTERS")
    assert out.panel["topic"] == "FILTERS"
    assert any("PE" in line for line in out.panel["lines"])


def test_status_message(demo_state):
    out = CommandEngine(demo_state).execute("STATUS")
    assert out.ok and out.kind == "message"
    assert "providers" in out.text
    assert "DEMO" in out.text


def test_watchlist_add_message(demo_state):
    out = CommandEngine(demo_state).execute("WATCHLIST ADD MSFT")
    assert out.ok and out.kind == "message"
    assert "MSFT" in out.text
    assert any(row["symbol"] == "MSFT" for row in demo_state.watchlists.rows())


def test_watchlist_alias(demo_state):
    out = CommandEngine(demo_state).execute("wl ADD AAPL")
    assert out.ok and out.kind == "message"


def test_portfolio_buy(demo_state):
    out = CommandEngine(demo_state).execute("PORTFOLIO BUY AAPL 10 250 2026-01-05")
    assert out.ok and out.kind == "message"
    assert "AAPL" in out.text
    assert demo_state.portfolio.holdings()[0]["symbol"] == "AAPL"


def test_screen_panel_autorun(demo_state):
    out = CommandEngine(demo_state).execute("SCREEN PE<100")
    assert out.ok and out.kind == "panel"
    assert out.panel["view"] == "screener"
    assert out.panel["filters"] == "PE<100"
    assert out.panel["autorun"] is True


def test_screen_save_load_delete(demo_state):
    engine = CommandEngine(demo_state)
    out = engine.execute("SCREEN SAVE T1 PE<50")
    assert out.ok and "T1" in out.text
    loaded = engine.execute("SCREEN LOAD T1")
    assert loaded.ok and loaded.panel["filters"] == "PE<50"
    out = engine.execute("SCREEN DELETE T1")
    assert out.ok
    assert "T1" in out.text
    assert engine.execute("SCREEN LOAD T1").ok is False


def test_compare_errors_on_single_symbol(demo_state):
    out = CommandEngine(demo_state).execute("COMPARE AAPL")
    assert not out.ok
    assert "usage: COMPARE" in out.text


def test_compare_panel(demo_state):
    out = CommandEngine(demo_state).execute("COMPARE AAPL MSFT")
    assert out.ok and out.kind == "panel"
    assert out.panel["view"] == "compare"
    assert out.panel["symbols"] == ["AAPL", "MSFT"]


def test_markets_panel(demo_state):
    out = CommandEngine(demo_state).execute("MARKETS")
    assert out.ok and out.panel["view"] == "markets"


def test_settings_get(demo_state):
    out = CommandEngine(demo_state).execute("SETTINGS GET data.demo_mode")
    assert out.ok and out.kind == "message"
    assert "True" in out.text


def test_workspace_save_needs_ui(demo_state):
    out = CommandEngine(demo_state).execute("WORKSPACE SAVE")
    assert not out.ok
    assert "no current view to save" in out.text


def test_workspace_lifecycle(demo_state):
    engine = CommandEngine(demo_state)
    out = engine.execute("WORKSPACE NEW focus")
    assert out.ok
    out = engine.execute("WORKSPACE USE focus")
    assert out.ok
    assert demo_state.settings.get("workspace.active") == "focus"


def test_history_records(demo_state):
    engine = CommandEngine(demo_state)
    engine.execute("HELP")
    out = engine.execute("HISTORY")
    assert out.ok and out.kind == "message"
    assert "HELP" in out.text


def test_bad_history_arg_errors(demo_state):
    out = CommandEngine(demo_state).execute("HISTORY notanumber")
    assert not out.ok
    assert out.kind == "error"


def test_planned_command_is_warn(demo_state):
    out = CommandEngine(demo_state).execute("ALERTS")
    assert out.ok
    assert out.level == "warn"
    assert "planned for a later phase" in out.text


def test_clear_kind(demo_state):
    out = CommandEngine(demo_state).execute("CLEAR")
    assert out.ok and out.kind == "clear"


def test_empty_command_is_noop(demo_state):
    out = CommandEngine(demo_state).execute("   ")
    assert out.ok and out.kind == "message"