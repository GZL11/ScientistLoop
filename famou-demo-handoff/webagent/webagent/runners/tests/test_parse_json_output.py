"""eval._parse_json_output 的单元测试。"""

from webagent.runners.eval import _parse_json_output


def test_clean_json():
    assert _parse_json_output('{"score": 0.5}') == {"score": 0.5}


def test_json_with_leading_warning():
    text = 'WARNING: something\n{"score": 0.5}'
    assert _parse_json_output(text) == {"score": 0.5}


def test_json_with_trailing_text():
    text = '{"score": 0.5}\nDone.'
    assert _parse_json_output(text) == {"score": 0.5}


def test_json_with_both():
    text = 'warn: x\n{"score": 0.5}\nok'
    assert _parse_json_output(text) == {"score": 0.5}


def test_empty_string():
    assert _parse_json_output("") is None


def test_no_json():
    assert _parse_json_output("just some text") is None


def test_whitespace_only():
    assert _parse_json_output("   \n  ") is None


def test_nested_json():
    text = 'log line\n{"a": {"b": 1}, "c": 2}\nend'
    result = _parse_json_output(text)
    assert result == {"a": {"b": 1}, "c": 2}


def test_broken_json():
    assert _parse_json_output('{"score": }') is None
