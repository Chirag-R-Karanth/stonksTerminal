from app.commands.tokenizer import Token, tokenize


def test_simple_filter_tokens():
    assert tokenize("PE<20") == [Token("WORD", "PE"), Token("OP", "<"), Token("NUMBER", "20")]


def test_exponent_number():
    tokens = tokenize("MARKETCAP>2e10")
    assert tokens[2] == Token("NUMBER", "2e10")
    assert float(tokens[2].value) == 2e10


def test_percent_number():
    tokens = tokenize("PE<20%")
    assert tokens[2] == Token("NUMBER", "20%")


def test_negative_and_decimal():
    tokens = tokenize("SCORE>=-1.5e-3")
    assert tokens == [
        Token("WORD", "SCORE"),
        Token("OP", ">="),
        Token("NUMBER", "-1.5e-3"),
    ]


def test_string_token():
    tokens = tokenize('FIND "apple inc"')
    assert tokens == [Token("WORD", "FIND"), Token("STRING", "apple inc")]


def test_equals_normalized_to_double():
    tokens = tokenize("A=B")
    assert tokens[1] == Token("OP", "==")


def test_words_preserved():
    tokens = tokenize("SBIN.NS ADD 10.5")
    assert tokens == [
        Token("WORD", "SBIN.NS"),
        Token("WORD", "ADD"),
        Token("NUMBER", "10.5"),
    ]


def test_iso_date_single_token():
    tokens = tokenize("2026-01-05")
    assert tokens == [Token("WORD", "2026-01-05")]
    assert tokenize("PORTFOLIO BUY AAPL 10 250 2026-01-05")[-1] == Token("WORD", "2026-01-05")
