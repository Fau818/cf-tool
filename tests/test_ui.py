"""ui.select: headings between groups, in the menu and in the typed fallback."""

from types import SimpleNamespace

import pytest
import questionary
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.output import DummyOutput
from questionary.prompts.common import InquirerControl

from cf_tool import ui

CHOICES = [("a.cpp", "a"), ("b.cpp", "b"), ui.Heading("── other files ──"), ("c.cpp", "c")]


def test_fallback_numbers_only_the_choices(monkeypatch, capsys):
    monkeypatch.setattr(ui, "interactive", lambda: False)
    monkeypatch.setattr(ui, "choose_index", lambda n: n - 1)  # the last of n
    assert ui.select("Which file?", CHOICES) == "c"
    lines = capsys.readouterr().out.splitlines()
    assert lines[1:] == ["  0: a.cpp", "  1: b.cpp", "     ── other files ──", "  2: c.cpp"]


DEFAULT = object()


def fake_questionary(monkeypatch, answer=DEFAULT):
    """questionary.select stand-in: records its arguments; asking it gives
    answer, or the default."""
    calls = []

    class Question:
        def __init__(self, kwargs):
            self.kwargs = kwargs
            self.application = SimpleNamespace(
                layout=SimpleNamespace(find_all_controls=list), key_bindings=KeyBindings()
            )

        def unsafe_ask(self):
            return self.kwargs["default"] if answer is DEFAULT else answer

    def select(message, **kwargs):
        calls.append(kwargs)
        return Question(kwargs)

    monkeypatch.setattr(ui, "interactive", lambda: True)
    monkeypatch.setattr(questionary, "select", select)
    return calls


def test_menu_shows_headings_as_separators(monkeypatch):
    calls = fake_questionary(monkeypatch)
    assert ui.select("Which file?", CHOICES, default="a") == "a"
    shown = calls[0]["choices"]
    assert isinstance(shown[2], questionary.Separator) and shown[2].title == "── other files ──"
    assert [c.value for c in shown if not isinstance(c, questionary.Separator)] == ["a", "b", "c"]
    assert calls[0]["use_shortcuts"] is True


def test_headings_do_not_count_as_shortcuts(monkeypatch):
    calls = fake_questionary(monkeypatch)
    choices = [(str(i), i) for i in range(ui.MAX_SHORTCUTS)]
    ui.select("Which?", choices[:1] + [ui.Heading("--")] + choices[1:], default=0)
    assert calls[0]["use_shortcuts"] is True
    assert calls[0]["use_jk_keys"] is False  # j and k are shortcuts of items 20 and 21


def test_filtering_drops_the_headings(monkeypatch):
    calls = fake_questionary(monkeypatch)
    ui.select("Which file?", CHOICES, default="a", search=True)
    assert not any(isinstance(c, questionary.Separator) for c in calls[0]["choices"])
    assert calls[0]["use_search_filter"] is True and calls[0]["use_shortcuts"] is False


def run_menu(monkeypatch, keys: str, **kwargs):
    """ui.select in a real (headless) questionary prompt fed with keys:
    (answer, the prompt's InquirerControl)."""
    made = []
    real_select = questionary.select

    def select(*args, **kw):
        made.append(real_select(*args, **kw))
        return made[-1]

    monkeypatch.setattr(ui, "interactive", lambda: True)
    monkeypatch.setattr(questionary, "select", select)
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        pipe.send_text(keys)
        answer = ui.select("Which file?", CHOICES, **kwargs)
    controls = made[0].application.layout.find_all_controls()
    return answer, next(c for c in controls if isinstance(c, InquirerControl))


def test_the_default_is_where_the_pointer_starts_not_a_painted_bar(monkeypatch):
    answer, control = run_menu(monkeypatch, "\r", default="b")
    assert answer == "b"
    assert control.selected_options == []  # questionary would paint it reverse-video
    styles = {style for style, _ in control._get_choice_tokens()}
    assert "class:selected" not in styles and "class:highlighted" in styles


def test_number_keys_pick_across_a_heading(monkeypatch):
    answer, _ = run_menu(monkeypatch, "3\r", default="a")
    assert answer == "c"  # the heading takes no number


@pytest.mark.parametrize("keys", ["\x1b", "\x1b\r"])
def test_escape_cancels(monkeypatch, capsys, keys):
    with pytest.raises(SystemExit):  # Esc+Enter used to answer "" (prompt_toolkit's Meta-Enter)
        run_menu(monkeypatch, keys, default="a")
    assert "Interrupted." in capsys.readouterr().out


def test_an_answer_that_is_no_item_is_a_cancel(monkeypatch, capsys):
    fake_questionary(monkeypatch, answer="")
    with pytest.raises(SystemExit):
        ui.select("Which file?", CHOICES, default="a")
    assert "Interrupted." in capsys.readouterr().out
