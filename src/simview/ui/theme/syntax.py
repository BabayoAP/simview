"""Code colors from the tokens: a Pygments style (editor and console) and the console's
stylesheet (prompts, errors). Built here so no color lives outside `ui/theme/`."""

from __future__ import annotations

from functools import cache

from pygments.style import Style
from pygments.token import (
    Comment,
    Error,
    Keyword,
    Name,
    Number,
    Operator,
    String,
    Text,
    Token,
    _TokenType,
)

from simview.ui.theme import tokens
from simview.ui.theme.tokens import ThemeName


@cache
def pygments_style(theme: ThemeName) -> type[Style]:
    c, s = tokens.COLORS[theme], tokens.SYNTAX[theme]
    styles: dict[_TokenType, str] = {
        Token: c["text.primary"],
        Text: c["text.primary"],
        Operator: c["text.primary"],
        Keyword: f"bold {s['keyword']}",
        Keyword.Constant: s["keyword"],
        Name.Builtin: s["builtin"],
        Name.Builtin.Pseudo: s["builtin"],
        Name.Function: s["function"],
        Name.Class: f"bold {s['class']}",
        Name.Decorator: s["decorator"],
        Name.Exception: s["class"],
        String: s["string"],
        String.Doc: s["comment"],
        Number: s["number"],
        Comment: f"italic {s['comment']}",
        Error: c["state.error"],
    }
    return type(
        f"SimView{theme.title()}Style",
        (Style,),
        {
            "background_color": c["bg.panel"],
            "highlight_color": c["accent.fill"],
            "styles": styles,
        },
    )


def console_stylesheet(theme: ThemeName) -> str:
    """qtconsole's `style_sheet`: the text area, prompts, and error output."""
    c = tokens.COLORS[theme]
    return f"""
QPlainTextEdit, QTextEdit {{
    background-color: {c["bg.panel"]};
    color: {c["text.primary"]};
    selection-background-color: {c["accent.fill"]};
    selection-color: {c["text.on_accent"]};
    border: none;
}}
.error {{ color: {c["state.error"]}; }}
.in-prompt {{ color: {c["accent"]}; }}
.in-prompt-number {{ font-weight: bold; }}
.out-prompt {{ color: {c["state.success"]}; }}
.out-prompt-number {{ font-weight: bold; }}
"""
