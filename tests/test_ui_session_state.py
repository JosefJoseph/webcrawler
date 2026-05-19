"""Static regression tests for Streamlit session_state widget rules.

Streamlit forbids writing to a session_state key that is owned by a widget
(i.e. assigned via key=) after the widget is instantiated in the same run.
Doing so raises StreamlitAPIException at runtime.

These tests parse the UI source files with the `ast` module to catch the
invalid pattern before it reaches the browser.
"""
import ast
import pathlib

MAIN_PAGE = pathlib.Path(__file__).parent.parent / "app" / "ui" / "pages" / "mainPage.py"

_WIDGET_CALLS = {"slider", "checkbox", "text_input", "text_area", "number_input",
                 "selectbox", "multiselect", "radio", "color_picker", "date_input",
                 "time_input", "file_uploader", "camera_input", "download_button"}


def _collect_widget_keys_and_post_writes(source: str) -> tuple[set[str], list[tuple[int, str]]]:
    """Return (widget_keys, post_instantiation_writes).

    widget_keys  – set of key= strings passed to any Streamlit widget call.
    post_instantiation_writes – list of (lineno, key) for session_state[key]=
      assignments that appear *after* the first widget with that key.
    """
    tree = ast.parse(source)
    body = tree.body  # top-level statements, in order

    # Collect (lineno, key) for every widget call that has a key= argument
    widget_key_lines: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = None
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        if name not in _WIDGET_CALLS:
            continue
        for kw in node.keywords:
            if kw.arg == "key" and isinstance(kw.value, ast.Constant):
                widget_key_lines.append((node.lineno, kw.value.value))

    widget_keys = {k for _, k in widget_key_lines}
    first_widget_line: dict[str, int] = {}
    for lineno, key in widget_key_lines:
        if key not in first_widget_line:
            first_widget_line[key] = lineno

    # Collect session_state[key] = ... assignments
    post_writes: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        # Match: st.session_state["key"] = ...  or  st.session_state['key'] = ...
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Subscript):
                continue
            val = target.value
            # Accept both `st.session_state[...]` and bare `session_state[...]`
            is_session_state = (
                (isinstance(val, ast.Attribute) and val.attr == "session_state")
                or (isinstance(val, ast.Name) and val.id == "session_state")
            )
            if not is_session_state:
                continue
            slice_node = target.slice
            if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
                key = slice_node.value
                if key in widget_keys:
                    widget_line = first_widget_line.get(key, 0)
                    if node.lineno > widget_line:
                        post_writes.append((node.lineno, key))

    return widget_keys, post_writes


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_post_widget_session_state_write_for_semantic_threshold():
    """mainPage.py must not write st.session_state['semantic_threshold'] after the slider.

    Violating this causes StreamlitAPIException at runtime.
    """
    source = MAIN_PAGE.read_text(encoding="utf-8")
    _, post_writes = _collect_widget_keys_and_post_writes(source)
    threshold_writes = [(ln, k) for ln, k in post_writes if k == "semantic_threshold"]
    assert not threshold_writes, (
        f"mainPage.py writes to st.session_state['semantic_threshold'] after the widget "
        f"is instantiated (Streamlit forbids this). Offending lines: {threshold_writes}"
    )


def test_no_post_widget_session_state_writes_any_key():
    """mainPage.py must not write to ANY widget-owned session_state key after instantiation."""
    source = MAIN_PAGE.read_text(encoding="utf-8")
    _, post_writes = _collect_widget_keys_and_post_writes(source)
    assert not post_writes, (
        f"mainPage.py writes to widget-owned session_state keys after widget instantiation "
        f"(Streamlit forbids this). Offending (line, key) pairs: {post_writes}"
    )


def test_semantic_threshold_default_is_not_085():
    """Default semantic_threshold must not be 0.85 — that value is too high for practical use."""
    source = MAIN_PAGE.read_text(encoding="utf-8")
    # Check the guard block initialises to something other than 0.85
    assert "semantic_threshold = 0.85" not in source, (
        "mainPage.py sets semantic_threshold default to 0.85, which is too restrictive."
    )


def test_crawl_page_reads_threshold_from_session_state():
    """crawlPage.py must read semantic_threshold from session_state, not use a hardcoded 0.85."""
    crawl_page = MAIN_PAGE.parent / "crawlPage.py"
    source = crawl_page.read_text(encoding="utf-8")
    assert 'session_state.get("semantic_threshold"' in source or \
           "session_state.get('semantic_threshold'" in source, (
        "crawlPage.py must read semantic_threshold from session_state."
    )
    # Must not fall back to 0.85
    assert 'get("semantic_threshold", 0.85)' not in source, (
        "crawlPage.py uses 0.85 as fallback for semantic_threshold — use 0.30 instead."
    )
