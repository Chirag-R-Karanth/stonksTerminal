import pytest

from app.commands.parser import Filter, ParseError, parse


def test_screen_filters():
    cmd = parse("SCREEN PE<20 DEBT/EQUITY<0.5")
    assert cmd.kind == "command"
    assert cmd.verb == "SCREEN"
    assert len(cmd.filters) == 2
    assert cmd.filters[0] == Filter("PE", "<", 20.0, "PE<20")
    assert cmd.filters[1].field == "DEBT/EQUITY"
    assert cmd.filters[1].value == 0.5


def test_exponent_filter_value():
    cmd = parse("SCREEN MARKETCAP>2e10")
    assert cmd.filters[0].value == 2e10


def test_percent_filter_value_is_fraction():
    cmd = parse("SCREEN PE<20%")
    assert cmd.filters[0].value == pytest.approx(0.2)


def test_symbol_with_action():
    cmd = parse("AAPL CHART")
    assert cmd.kind == "symbol"
    assert cmd.symbol == "AAPL"
    assert cmd.action == "CHART"
    assert cmd.args == []


def test_symbol_with_period_arg():
    cmd = parse("AAPL 1Y")
    assert cmd.kind == "symbol"
    assert cmd.symbol == "AAPL"
    assert cmd.action == ""
    assert cmd.args == ["1Y"]


def test_dotted_and_caret_symbols():
    assert parse("BRK.B FIN").symbol == "BRK.B"
    assert parse("^GSPC").symbol == "^GSPC"
    assert parse("RELIANCE.NS").symbol == "RELIANCE.NS"


def test_alias_verb():
    cmd = parse("wl ADD MSFT")
    assert cmd.kind == "command"
    assert cmd.verb == "WATCHLIST"
    assert cmd.args == ["ADD", "MSFT"]


def test_quoted_string_argument():
    cmd = parse('FIND "apple inc"')
    assert cmd.verb == "FIND"
    assert cmd.args == ["apple inc"]


def test_filters_attach_to_symbol_command():
    cmd = parse("AAPL PE<30")
    assert cmd.kind == "symbol"
    assert cmd.symbol == "AAPL"
    assert len(cmd.filters) == 1


def test_text_roundtrip():
    assert parse("SCREEN PE<20").text == "SCREEN PE<20"


@pytest.mark.parametrize("bad", ["", "   ", "PE<20"])
def test_parse_errors(bad):
    with pytest.raises(ParseError):
        parse(bad)
