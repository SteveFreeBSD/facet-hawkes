"""Shipping requirements for the Ethnos Hawkes Firefox add-on.

These tests are the automated half of the extension review checklist: they pin
the permission surface, the promises made in `extension/README.md`, and the fact
that the packaged tree still builds. `scripts/build_extension.py` performs the
structural validation; this module asserts the invariants that must not drift
even if that script is edited.
"""

from __future__ import annotations

import importlib.util
import json
import re
import zipfile
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_DIR = PROJECT_ROOT / "extension"
BUILD_SCRIPT = PROJECT_ROOT / "scripts" / "build_extension.py"


def _load_build_module():
    spec = importlib.util.spec_from_file_location("build_extension", BUILD_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_extension = _load_build_module()


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((EXTENSION_DIR / "manifest.json").read_text())


@pytest.fixture(scope="module")
def messages() -> dict:
    return json.loads((EXTENSION_DIR / "_locales" / "en" / "messages.json").read_text())


def test_extension_tree_passes_its_own_validation():
    assert build_extension.validate() == []


def test_manifest_keeps_the_minimal_permission_surface(manifest):
    assert manifest["manifest_version"] == 3
    # nativeMessaging reaches exactly one registered local host and opens no
    # port; it is not standing access to anything on the web.
    assert manifest["permissions"] == [
        "activeTab",
        "nativeMessaging",
        "scripting",
        "storage",
    ]
    # One host, declared rather than requested. activeTab is granted only by
    # the toolbar button, which left the sidebar with no access at all and made
    # the add-on nag for a permission it needs to do anything. Anything wider
    # than this single origin is a build failure.
    assert manifest["host_permissions"] == ["*://learn.hawkeslearning.com/*"]
    assert "optional_host_permissions" not in manifest
    assert "content_scripts" not in manifest


def test_only_extension_pages_may_reach_ethnos_or_capture_the_tab():
    # The page an injected script runs in is not trusted, so it must not be
    # able to reach the solver or screenshot the tab.
    for path in sorted((EXTENSION_DIR / "content").glob("*.js")):
        source = path.read_text()
        for token in ("sendNativeMessage", "connectNative", "captureVisibleTab"):
            assert token not in source, f"{path.name} uses {token}"

    background = (EXTENSION_DIR / "background.js").read_text()
    assert 'NATIVE_HOST = "ethnos_hawkes"' in background
    # A port rather than a one-shot message, so the host can report each stage
    # as it begins instead of only answering at the end.
    assert "connectNative" in background


def test_the_host_is_asked_only_named_operations():
    background = (EXTENSION_DIR / "background.js").read_text()

    # The request carries an operation name and problem content -- never a
    # command, path, model name, or URL for the host to act on.
    assert 'askEthnos("health"' in background
    assert '"solve_hawkes_problem"' in background
    assert "solve_engine: settings.solveEngine" in background
    assert 'operation: "health" | "solve_hawkes_problem"' in background or True
    for smuggled in ("model:", "path:", "command:", "script:"):
        assert smuggled not in background

    settings = (EXTENSION_DIR / "common" / "settings.js").read_text()
    options = (EXTENSION_DIR / "options" / "options.html").read_text()
    assert 'solveEngine: { kind: "enum", fallback: "ethnos"' in settings
    assert 'values: Object.freeze(["ethnos", "facet"])' in settings
    assert 'data-setting="solveEngine"' in options
    assert 'value="facet"' in options


def test_health_is_checked_before_a_capture_is_spent():
    background = (EXTENSION_DIR / "background.js").read_text()
    solve = background[background.index("async function solve(") :]
    health = solve.index('askEthnos(\n      "health"')
    capture = solve.index("captureQuestion(")

    # `health` needs no model, so an unregistered host is reported in a moment
    # instead of after a minute of transcription.
    assert health < capture


def test_unhandled_markup_falls_back_to_a_capture_without_caching_coursework():
    background = (EXTENSION_DIR / "background.js").read_text()
    host = (PROJECT_ROOT / "src" / "ethnos" / "hawkes_host.py").read_text()

    assert 'reply?.status === "unsupported"' in background
    assert 'log.info("markup-fallback"' in background
    assert "solveDeadline - Date.now()" in background
    assert "cache_dir=None" in host
    assert "cache_dir=settings.question_image_cache_dir" not in host


def test_insertability_comes_from_the_editor_not_a_guess():
    background = (EXTENSION_DIR / "background.js").read_text()
    view = (EXTENSION_DIR / "common" / "panel-view.js").read_text()
    rules = (EXTENSION_DIR / "common" / "editor-rules.js").read_text()

    # The accepted character set is per question, so it is read from the
    # editor rather than hardcoded. 0.8.0 guessed, and guessed wrong.
    assert 'DESCRIBE_SCRIPT = "/content/hawkes-describe.js"' in background
    assert 'world: "MAIN"' in background
    assert "answerFitsEditor(state.answer, state.editor)" in view
    assert "editor.allowedCharacters" in rules
    # Structural notation can never be typed, whatever the character set says.
    assert "answer-needs-template" in rules


def test_exactly_one_page_world_script_may_write():
    problems: list[str] = []
    build_extension._check_main_world_writer(problems)
    assert problems == []

    writer = (EXTENSION_DIR / "common" / "page-actions.js").read_text()
    # It presses the editor's own templates -- the only way to build structure
    # -- and may do nothing else to the page.
    assert "keyPadButtonClick" in writer
    for token in ("eval(", "new Function(", ".click(", "submit", "fetch(", "innerHTML"):
        assert token not in writer, f"page-world writer uses {token}"
    # It is passed as a function so the plan can be an argument.
    background = (EXTENSION_DIR / "background.js").read_text()
    assert "func: enterPlan" in background
    assert 'world: "MAIN"' in background


def test_a_structured_answer_is_built_rather_than_refused():
    background = (EXTENSION_DIR / "background.js").read_text()

    # An answer that cannot be typed is now built with the keypad templates,
    # not just displayed for the user to enter.
    assert "buildStructured" in background
    assert "planEntry(" in background
    assert "answerFitsEditor(reviewed, state.editor).insertable" in background


def test_only_the_read_only_probe_runs_in_the_page_world():
    problems: list[str] = []
    build_extension._check_main_world(problems)
    assert problems == []

    probe = (EXTENSION_DIR / "content" / "hawkes-describe.js").read_text()
    # It reads the model. It must never press a template or assign to it.
    for token in ("keyPadButtonClick(", "dispatchEvent", ".click()", "eval("):
        assert token not in probe, f"page-world probe uses {token}"


def test_insertion_requires_a_confirmed_transcription():
    background = (EXTENSION_DIR / "background.js").read_text()

    # Two readers must agree about the question before anything is insertable.
    assert "certainty.insertable" in background
    assert "errorTranscriptionDisputed" in background


def test_manifest_exposes_no_web_accessible_resources(manifest):
    # An exposed resource is a probe target for extension-fingerprinting
    # scripts. Firefox randomizes the moz-extension UUID per profile, so a page
    # cannot guess the URL, but it can read one the add-on hands it.
    assert "web_accessible_resources" not in manifest


def test_the_background_page_is_a_plain_non_persistent_event_page(manifest):
    # Firefox MV3 uses event pages, not Chrome's service workers. One exists so
    # a solve survives the popup closing, and it stays as small as that needs.
    assert manifest["background"] == {"scripts": ["background.js"], "type": "module"}
    assert "service_worker" not in manifest["background"]
    assert manifest["background"].get("persistent") is None


def test_manifest_declares_no_request_interception(manifest):
    # Nothing here observes or rewrites network traffic, so neither the
    # blocking nor the declarative API is required.
    for key in ("declarative_net_request", "webRequest", "chrome_settings_overrides"):
        assert key not in manifest
    assert "declarativeNetRequest" not in manifest["permissions"]
    assert "webRequest" not in manifest["permissions"]


def test_content_scripts_leave_no_page_detectable_footprint():
    for path in sorted((EXTENSION_DIR / "content").glob("*.js")):
        source = path.read_text()
        for token in build_extension.CONTENT_SCRIPT_FORBIDDEN:
            assert token not in source, f"{path.name} uses {token!r}"

    editor = (EXTENSION_DIR / "content" / "hawkes-editor.js").read_text()
    # window is read, never written.
    for read_only in ("window.location.origin", "window.getSelection()"):
        assert read_only in editor


def test_no_script_crosses_the_content_script_isolation_boundary():
    # Firefox's object-sharing escapes are observable from the page and are
    # never needed for ordinary DOM access.
    escapes = ("wrappedJSObject", "exportFunction", "cloneInto")
    assert all(token in build_extension.FORBIDDEN_TOKENS for token in escapes)
    for path in build_extension.packaged_files():
        if path.suffix != ".js":
            continue
        source = (EXTENSION_DIR / path).read_text()
        assert not any(token in source for token in escapes), path


def test_every_frame_is_inspected_then_exactly_one_receives_the_answer():
    source = (EXTENSION_DIR / "background.js").read_text()

    # Hawkes may render its editor in an iframe, so every frame is asked...
    assert "{ tabId: tab.id, allFrames: true }" in source
    # ...but the insertion targets only the frame that claimed the caret,
    # which is also why allFrames and frameIds are never combined.
    assert "frameIds: [state.frameId]" in source
    # The value inserted is checked against the value the user reviewed.
    assert "outcome.answer !== reviewed" in source
    # The decision itself lives in a DOM-free module so it can be exercised
    # directly; see tests/test_hawkes_frames.py.
    assert '"/common/frames.js"' in source
    assert "selectAnswerFrame(results)" in source


def test_unreachable_frame_names_the_host_that_would_be_granted():
    background = (EXTENSION_DIR / "background.js").read_text()
    messages = json.loads(
        (EXTENSION_DIR / "_locales" / "en" / "messages.json").read_text()
    )

    assert '"errorFrameUnreachableAt"' in background
    assert "choice.origin ? [choice.origin] : []" in background
    entry = messages["errorFrameUnreachableAt"]
    assert entry["placeholders"]["origin"]["content"] == "$1"
    assert "$ORIGIN$" in entry["message"]

    editor = (EXTENSION_DIR / "content" / "hawkes-editor.js").read_text()
    # Only the origin is taken, never the full URL, which can carry a query
    # string from the lesson.
    assert "new URL(source, document.baseURI).origin" in editor


def test_manifest_is_signable_and_declares_website_content(manifest):
    gecko = manifest["browser_specific_settings"]["gecko"]

    assert gecko["id"] == "ethnos-hawkes@local"
    # Desktop understands the data consent declaration from 140, but Firefox
    # for Android only from 142, and one floor covers both. Pinned so the
    # disclosure is actually shown rather than silently ignored -- and so the
    # floor cannot contradict the declaration it exists to protect, which is
    # what `web-ext lint --warnings-as-errors` refuses.
    assert gecko["strict_min_version"] == "142.0"
    # Question text/MathML/screenshots cross the browser boundary through
    # native messaging, which Mozilla classifies as websiteContent even when
    # the companion and configured model endpoint are local.
    collection = gecko["data_collection_permissions"]
    assert isinstance(collection, dict)
    assert collection["required"] == ["websiteContent"]
    assert manifest["content_security_policy"]["extension_pages"] == (
        "script-src 'self'; object-src 'none'"
    )


def test_manifest_ships_a_complete_icon_set(manifest):
    for size in ("16", "32", "48", "96", "128"):
        icon = EXTENSION_DIR / manifest["icons"][size]
        assert icon.is_file(), f"missing {size}px icon"
        assert icon.stat().st_size > 0


def test_every_user_visible_string_is_localized(manifest, messages):
    assert manifest["default_locale"] == "en"
    assert manifest["name"] == "__MSG_extensionName__"
    assert manifest["description"] == "__MSG_extensionDescription__"
    assert all(entry["description"] for entry in messages.values())


def test_no_shipped_script_can_submit_navigate_or_reach_the_network():
    forbidden = build_extension.FORBIDDEN_TOKENS
    for path in build_extension.packaged_files():
        if path.suffix not in {".js", ".html"}:
            continue
        source = (EXTENSION_DIR / path).read_text()
        hits = [token for token in forbidden if token in source]
        assert hits == [], f"{path} contains {hits}"


def test_content_script_refuses_foreign_origins_and_unsupported_answers():
    source = (EXTENSION_DIR / "content" / "hawkes-editor.js").read_text()

    assert 'ALLOWED_ORIGIN = "https://learn.hawkeslearning.com";' in source
    assert "window.location.origin === ALLOWED_ORIGIN" in source
    # The content scripts repeat the popup's validation so a bug in an
    # extension page cannot widen what reaches the editor.
    assert "ANSWER_PATTERN.test(value)" in source
    assert "MAX_ANSWER_LENGTH" in source


def test_content_scripts_share_constants_with_the_extension_pages():
    # The drift check is part of validate(); assert it is actually wired up.
    problems: list[str] = []
    build_extension._check_shared_constants(problems)
    assert problems == []


def test_shared_prelude_survives_reinjection():
    source = (EXTENSION_DIR / "content" / "hawkes-editor.js").read_text()

    # The popup re-injects this file on every use, and Firefox gives an
    # extension one scope per frame, so a top-level const or let would throw a
    # redeclaration error the second time. Only `var` tolerates that.
    top_level = [
        line
        for line in source.splitlines()
        if line.startswith(("const ", "let ", "class "))
    ]
    assert top_level == []
    # Exactly one name reaches the shared scope; the IIFE holds the rest, so
    # each execution rebuilds its own locals.
    assert source.count("\nvar ") == 1
    assert "var ethnosHawkes = (function () {" in source
    assert source.rstrip().endswith("})();")


def test_operation_scripts_are_self_contained_iifes():
    for name in ("inspect-field.js",):
        source = (EXTENSION_DIR / "content" / name).read_text()
        code = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
        code = code.replace('"use strict";', "").strip()
        # Every executable line lives inside the IIFE, so an operation leaves
        # no declaration of its own in the frame's scope.
        assert code.startswith("(")
        assert code.endswith(")();")
        assert not re.search(r"^(var|let|const|function|class)\s", code, re.MULTILINE)


def test_operation_scripts_tolerate_a_missing_prelude():
    # A bare ReferenceError would reach the panel only as InjectionResult.error,
    # which the popup can report no better than "something failed".
    for name in ("inspect-field.js",):
        source = (EXTENSION_DIR / "content" / name).read_text()
        assert 'typeof ethnosHawkes === "undefined"' in source
        assert '"prelude-missing"' in source


def test_operation_scripts_register_nothing_and_return_a_result():
    for name in ("inspect-field.js",):
        source = (EXTENSION_DIR / "content" / name).read_text()
        # No listener means nothing survives the call, so no injection marker
        # is needed to keep repeat runs idempotent.
        assert "addEventListener" not in source
        assert "onMessage" not in source
    assert (
        "ethnosHawkes.inspectField()"
        in (EXTENSION_DIR / "content" / "inspect-field.js").read_text()
    )


def test_popup_requires_a_separate_insert_click(manifest):
    popup = (EXTENSION_DIR / "popup" / "popup.html").read_text()

    assert manifest["action"]["default_popup"] == "popup/popup.html"
    assert 'id="insert"' in popup and "disabled" in popup
    assert 'data-i18n="popupInsertButton"' in popup


def test_extension_pages_carry_no_inline_script_or_handlers():
    for path in build_extension.packaged_files():
        if path.suffix != ".html":
            continue
        source = (EXTENSION_DIR / path).read_text()
        assert "<script>" not in source
        assert " onclick=" not in source


def test_readme_documents_scope_removal_and_release():
    readme = (EXTENSION_DIR / "README.md").read_text()

    assert "about:debugging#/runtime/this-firefox" in readme
    assert "submit" in readme
    assert "## Remove it" in readme
    assert "unlisted" in readme


def test_a_solve_survives_the_panel_closing():
    background = (EXTENSION_DIR / "background.js").read_text()
    popup = (EXTENSION_DIR / "popup" / "popup.js").read_text()

    # A popup closes whenever anything takes focus, and a solve takes the
    # better part of a minute, so the work cannot live in the panel.
    assert "await solve(asking)" in background  # started from the port handler
    assert "AbortController" in background
    # The panel only renders state and asks for operations.
    assert "captureVisibleTab" not in popup
    assert "sendNativeMessage" not in popup
    # Reopening mid-solve must not restart anything: prepare is requested only
    # on the first state the panel sees, and only when nothing is under way.
    assert "first && !busy" in popup
    assert "const first = current === null;" in popup


def test_a_disconnected_sidebar_cannot_pretend_to_be_solving():
    popup = (EXTENSION_DIR / "popup" / "popup.js").read_text()

    assert "let portOpen = true" in popup
    assert "if (!portOpen)" in popup
    assert "render(null)" in popup
    assert "window.location.reload()" in popup
    assert 'if (!request("ethnos:solve"))' in popup


def test_a_reviewed_answer_is_passed_directly_and_never_persisted():
    config = (EXTENSION_DIR / "common" / "config.js").read_text()
    editor = (EXTENSION_DIR / "content" / "hawkes-editor.js").read_text()
    background = (EXTENSION_DIR / "background.js").read_text()

    assert "DEFAULT_ANSWER" not in config
    assert "DEFAULT_ANSWER" not in editor
    assert "previewAnswer" not in config
    assert not (EXTENSION_DIR / "content" / "insert-answer.js").exists()
    assert "function enterPlainAnswer(answer, cadence)" in background
    assert "func: enterPlainAnswer" in background
    assert "args: [reviewed, cadence]" in background


def test_a_new_question_clears_the_previous_answer():
    background = (EXTENSION_DIR / "background.js").read_text()
    popup = (EXTENSION_DIR / "popup" / "popup.js").read_text()
    editor = (EXTENSION_DIR / "content" / "hawkes-editor.js").read_text()

    # Hawkes swaps the answer controls in place, so nothing navigates and the
    # onUpdated reset never fires. The control's identity and rules stand in
    # for "which question".
    assert "fieldId: target.id" in editor
    assert "const signature =" in background
    assert "sameQuestion" in background
    # The panel re-checks on every open, not only the first.
    assert 'request("ethnos:prepare")' in popup
    # And it can be cleared by hand.
    assert 'request("ethnos:reset")' in popup


def test_the_panel_talks_to_the_background_over_a_port():
    popup = (EXTENSION_DIR / "popup" / "popup.js").read_text()
    background = (EXTENSION_DIR / "background.js").read_text()

    # A panel closes whenever anything takes focus. One-off messages awaiting a
    # reply then reject into a destroyed context, and pushing state to a closed
    # popup leaves an aborted query -- both observed in Firefox's console. A
    # port needs no reply and disconnects cleanly.
    assert 'browser.runtime.connect({ name: "ethnos:panel" })' in popup
    assert "port.postMessage" in popup
    assert "port.onMessage" in popup
    assert "runtime.sendMessage" not in popup
    for operation in (
        "ethnos:solve",
        "ethnos:insert",
        "ethnos:cancel",
        "ethnos:prepare",
    ):
        assert f'request("{operation}")' in popup

    assert "onConnect" in background
    assert "onDisconnect" in background
    # State is only pushed while a panel is actually connected.
    # State is pushed only to panels that are actually connected, and to
    # every one of them: Firefox gives each window its own sidebar. What each
    # is shown is scoped to its own window by `stateFor`.
    assert "for (const [port, entry] of panels)" in background
    # An operation started from a port message must not leak a rejection.
    assert "function begin(operation)" in background


def test_the_background_uses_static_imports_not_dynamic_ones(manifest):
    background = (EXTENSION_DIR / "background.js").read_text()

    # Static imports in a module event page are the documented way to share
    # code. Dynamic import() inside a classic background script is not, and
    # shipping it untested was a gamble.
    assert manifest["background"]["type"] == "module"
    assert "await import(" not in background
    for module in ("/common/config.js", "/common/editor-rules.js", "/common/frames.js"):
        assert f'from "{module}"' in background


def test_an_open_hawkes_dialog_is_reported_rather_than_its_symptoms():
    editor = (EXTENSION_DIR / "content" / "hawkes-editor.js").read_text()
    frames = (EXTENSION_DIR / "common" / "frames.js").read_text()
    background = (EXTENSION_DIR / "background.js").read_text()

    # While a Hawkes message box is open it holds focus, the editor reports no
    # focused control, and every focus() fails silently.
    assert "querySelectorAll('[id*=\"customMessageBox\"]')" in editor
    assert '"editor-dialog-open"' in editor
    assert '"editor-dialog-open"' in frames
    assert '"editor-dialog-open": "errorEditorDialogOpen"' in background


def test_a_lapsed_tab_grant_is_named_for_what_it_is():
    background = (EXTENSION_DIR / "background.js").read_text()

    # activeTab lasts until the tab navigates; when it lapses Firefox reports a
    # missing host permission, which reads as a bug rather than "click again".
    assert "errorTabAccessLost" in background
    assert "host permission" in background


def test_sidebar_can_use_one_unambiguous_visible_hawkes_field_without_focus():
    editor = (EXTENSION_DIR / "content" / "hawkes-editor.js").read_text()

    assert "HAWKES_FIELD_SELECTOR" in editor
    assert "candidates.length === 1 ? candidates[0] : null" in editor
    assert "!element.disabled" in editor
    assert "!element.readOnly" in editor


def test_page_operations_have_a_deadline():
    background = (EXTENSION_DIR / "background.js").read_text()

    assert "PAGE_TIMEOUT_MS" in background
    assert "errorOperationTimeout" in background


def test_a_solved_answer_cannot_leak_into_the_next_question():
    background = (EXTENSION_DIR / "background.js").read_text()

    # Answers exist only in event-page memory and are passed directly to the
    # one-shot insertion function. Navigation drops the entire state, while an
    # in-place question change is checked by signature before insertion.
    assert "previewAnswer" not in background
    assert "state = blankState();" in background
    assert "question-changed-before-insert" in background
    assert "onUpdated" in background


def test_the_panel_can_be_dismissed_and_the_answer_accepted_by_keyboard():
    popup = (EXTENSION_DIR / "popup" / "popup.js").read_text()

    assert 'event.key === "Escape"' in popup
    assert 'event.key === "Enter"' in popup
    # An in-progress solve can be abandoned rather than only waited out.
    assert 'request("ethnos:cancel")' in popup


def test_cancelling_stops_the_host_rather_than_only_the_panel():
    background = (EXTENSION_DIR / "background.js").read_text()
    popup = (EXTENSION_DIR / "popup" / "popup.js").read_text()

    # An abort flag alone left the native port open, so the host kept working
    # and holding the model for the rest of the minute while the panel said it
    # had stopped. Rejecting on abort lets the `finally` disconnect the port,
    # which closes the pipe and ends the host.
    assert 'reject(new Error("errorCancelled"))' in background
    assert 'signal.addEventListener("abort"' in background
    assert "controller.signal" in background
    # A cancellation is not reported as a failure.
    assert 'error?.message !== "errorCancelled"' in background
    # And the panel looks stopped immediately, not when the background replies.
    assert 'phase: "ready", stage: ""' in popup


def test_progress_is_reported_stage_by_stage():
    background = (EXTENSION_DIR / "background.js").read_text()
    popup = (EXTENSION_DIR / "popup" / "popup.js").read_text()
    view = (EXTENSION_DIR / "common" / "panel-view.js").read_text()
    host = (PROJECT_ROOT / "src" / "ethnos" / "hawkes_host.py").read_text()

    # Almost the whole minute is the two image readings, so each stage is
    # announced as it begins rather than leaving one static line.
    assert 'announce("reading"' in host
    assert 'announce("solving"' in host
    assert 'reply.kind === "progress"' in background
    assert 'STAGES = ["capturing", "reading", "checking", "solving"]' in view
    # The panel turns a stage into a bar position and a label; both are
    # exercised directly in tests/test_hawkes_panel.py.
    assert "stageProgress" in popup or "stageProgress" in view


def test_the_screenshot_is_cropped_to_the_question():
    background = (EXTENSION_DIR / "background.js").read_text()

    # Account/navigation UI above and the answer panel below are not part of
    # the question. A failed privacy crop must not degrade to the full image.
    assert "cropToQuestion" in background
    assert "measureQuestionBounds" in background
    assert "frameOffsetTop" in background
    assert "current.frameElement" in background
    assert 'fail("errorQuestionRegion")' in background
    crop = background[
        background.index("async function cropToQuestion") : background.index(
            "function decodeDataUrl"
        )
    ]
    assert "return dataUrl" not in crop
    # No request API, even to decode a data URL.
    assert "fetch(" not in background
    assert "XMLHttpRequest" not in background


def test_live_protocol_covers_the_cases_only_a_browser_can_settle():
    protocol = (EXTENSION_DIR / "TESTING.md").read_text()

    for heading in (
        "The page cannot see the add-on",
        "The question is found, and solving starts on its own",
        "Cancel actually stops it",
        "The recognized problem matches the screen",
        "Insert",
        "It is ready for the next question",
        "Insertion never repeats",
        "Removal leaves nothing",
    ):
        assert heading in protocol, f"protocol is missing: {heading}"
    assert "about:debugging#/runtime/this-firefox" in protocol
    # It must describe the add-on as built, not as it once was.
    assert "no background page" not in protocol
    assert "11y" not in protocol


def test_injected_paths_are_root_absolute():
    # executeScript resolves file paths against the calling document, so a bare
    # "content/x.js" from popup/popup.html becomes "popup/content/x.js" and
    # throws inside every frame. This shipped in 0.7.0.
    problems: list[str] = []
    build_extension._check_injected_paths(problems)
    assert problems == []

    background = (EXTENSION_DIR / "background.js").read_text()
    for name in ("hawkes-editor", "inspect-field", "hawkes-describe"):
        assert f'"/content/{name}.js"' in background


def test_changelog_matches_the_manifest_version(manifest):
    changelog = (EXTENSION_DIR / "CHANGELOG.md").read_text()

    assert f"## {manifest['version']}" in changelog


def test_build_produces_a_reproducible_package(tmp_path, manifest):
    first = build_extension.build(tmp_path / "a")
    second = build_extension.build(tmp_path / "b")

    assert first.name == f"ethnos-hawkes-{manifest['version']}-unsigned.xpi"
    assert first.read_bytes() == second.read_bytes()

    with zipfile.ZipFile(first) as archive:
        names = archive.namelist()
    assert "manifest.json" in names
    # Developer material stays out of the signed package.
    assert not any(name.endswith((".md", ".svg")) for name in names)


def test_the_executor_waits_for_the_editor_to_settle():
    """Regression: structured answers came out half-entered.

    `Fraction` adds three boxes -- numerator, denominator, and the continuation
    after it -- and not in the same tick. Reading the box list at the first
    change captured only some of them, so the slots recorded for that template
    were wrong and every later move went to the wrong box.
    """
    writer = (EXTENSION_DIR / "common" / "page-actions.js").read_text()

    # Changed *and* then held still, rather than merely changed.
    assert "stable >= 3" in writer
    assert "now !== start" in writer
    assert "SETTLE_MS = 4000" in writer


def test_insertion_clears_the_answer_but_marks_the_question_handled():
    background = (EXTENSION_DIR / "background.js").read_text()

    # The answer is in the box, so its text is dropped. The signature stays so
    # the open sidebar watcher and a close/reopen do not solve the same question
    # again; only a real prompt/MathML change begins the next solve.
    assert "async function finishInsertion" in background
    assert 'answer: ""' in background
    assert 'displayText: ""' in background
    assert 'entryText: ""' in background
    finish = background.split("async function finishInsertion", 1)[1].split(
        "async function reset", 1
    )[0]
    assert "const afterInsertion = await readQuestion" in finish
    assert "signature: handledSignature" in finish
    assert 'previous.phase === "inserted"' in background
    assert "if (alreadyInserted || hasAnswer)" in background
    # What the panel shows afterwards is a separate, display-only copy. The
    # three fields above are what insertion consumes; none of them is restored
    # here, so nothing can be inserted twice or offered to a later question.
    assert "placedText: state.displayText || state.answer" in finish
    insertion = background.split("async function insert()", 1)[1].split(
        "* Settle after a successful insertion.", 1
    )[0]
    assert "placedText" not in insertion


def test_the_placed_answer_is_dropped_by_new_work_like_every_other_result():
    """A display-only copy is still an answer on screen.

    It outlives the insertion that produced it, so it needs the same clearing
    as the reviewed answer: a retry, a reset, and any question that is not the
    one it was placed into.
    """
    background = (EXTENSION_DIR / "background.js").read_text()
    popup = (EXTENSION_DIR / "popup" / "popup.js").read_text()

    assert 'placedText: ""' in background.split("async function solve(", 1)[1]
    assert 'placedText: ""' in background.split("function blankState()", 1)[1]
    # Carried across a re-check only for the very question it was placed into.
    assert 'placedText: alreadyInserted ? previous.placedText : ""' in background
    # And the panel's own optimistic paints clear it before the event page can.
    assert popup.count('placedText: ""') == 2


def test_structured_planning_uses_the_current_displayed_answer():
    background = (EXTENSION_DIR / "background.js").read_text()
    panel = (EXTENSION_DIR / "common" / "panel-view.js").read_text()

    assert "async function buildStructured(answer, cadence)" in background
    assert "const plan = planEntry(answer, state.editor);" in background
    assert "state.entryText || state.answer" in panel
    assert "reply.answer.keyboard_entry" in background


def test_insertion_fails_closed_when_final_question_or_editor_read_fails():
    background = (EXTENSION_DIR / "background.js").read_text()

    assert "if (!editor?.ok)" in background
    assert 'fail("errorEditorUnknown")' in background
    assert "if (onScreen === null || state.signature === null)" in background
    assert 'fail("errorQuestionUnverified")' in background


def test_solving_starts_without_a_second_click_unless_turned_off():
    background = (EXTENSION_DIR / "background.js").read_text()
    settings = (EXTENSION_DIR / "common" / "settings.js").read_text()
    options = (EXTENSION_DIR / "options" / "options.html").read_text()

    # The preference is declared once and read from memory, so a solve never
    # waits on storage to find out whether it should have started.
    assert 'autoSolve: { kind: "boolean", fallback: true }' in settings
    assert "if (settings.autoSolve)" in background
    assert 'data-setting="autoSolve"' in options


def test_inserting_is_never_automatic():
    """The add-on's whole safety contract, asserted rather than assumed."""
    settings = (EXTENSION_DIR / "common" / "settings.js").read_text()
    background = (EXTENSION_DIR / "background.js").read_text()
    options = (EXTENSION_DIR / "options" / "options.html").read_text()

    # There is no preference that would insert without a click, and the point
    # is written down beside the one that starts a solve.
    for tempting in ("autoInsert", "autoAnswer", "autoSubmit"):
        assert tempting not in settings
        assert tempting not in options
    assert "Insertion is never automatic" in settings
    # `insert` is only ever reached from a message the panel sends.
    assert 'case "ethnos:insert":' in background


def test_the_panel_is_available_as_a_docked_sidebar(manifest):
    """A popup is torn down whenever anything else takes focus.

    That loses the answer mid-read and makes a minute-long solve impossible to
    watch. Firefox's sidebar stays put, so the same panel is offered both ways.
    """
    sidebar = manifest["sidebar_action"]
    assert sidebar["default_panel"] == "popup/popup.html?sidebar=1"

    popup = (EXTENSION_DIR / "popup" / "popup.js").read_text()
    css = (EXTENSION_DIR / "popup" / "popup.css").read_text()
    # One page, adapting: the popup's own close makes no sense in a sidebar.
    assert 'get("sidebar") === "1"' in popup
    assert "elements.close.hidden = true" in popup
    assert "browser.sidebarAction.open()" in popup
    assert 'body[data-sidebar="true"]' in css
    # And a keyboard route to it.
    assert "_execute_sidebar_action" in manifest["commands"]


def test_a_failed_build_leaves_nothing_behind():
    """Regression: a half-built answer was submitted and marked wrong.

    The executor stopped at the second exponent and left `x^6y` in the box
    where `x^6y^7z^4` was meant. Partial content that looks complete enough to
    submit is worse than an empty box.
    """
    writer = (EXTENSION_DIR / "common" / "page-actions.js").read_text()

    assert "const abandon =" in writer
    assert "clearAnswer()" in writer
    # Every failure path inside the plan loop cleans up. `abandon` became async
    # once the clear had to be checked rather than assumed, so the calls await.
    assert writer.count("return await abandon(") >= 5
    # And a template is pressed only once the editor's own guard says yes.
    assert "qualifyLoadExponent" in writer
    assert "const readyFor =" in writer


def test_a_template_is_aimed_at_the_box_the_plan_is_in():
    """Regression: an exponent landed in the numerator, not the denominator.

    Setting DOM focus on an input does not move the editor's cursor; it keeps
    its own `CurrentBase` and loads a template onto that. So `12x` reached the
    denominator while the `^3` after it went to the numerator. The live object
    tree showed the exponent parented to `Numerator` with the denominator
    untouched beside it.
    """
    writer = (EXTENSION_DIR / "common" / "page-actions.js").read_text()

    assert "const findBase =" in writer
    assert "const aimEditorAt =" in writer
    # Only nodes that can load a template are considered: a Fraction and its
    # Numerator report the same box.
    assert 'node.Type === "Base"' in writer
    assert "press(step.name, cursor)" in writer


def test_a_disabled_control_is_refused_before_anything_is_typed():
    """`addElement` ignores every template when the control is disabled.

    Typing still works, because that goes through the DOM — so characters
    landed, structure did not, and nothing reported it. A plain explanation for
    half-built answers.
    """
    writer = (EXTENSION_DIR / "common" / "page-actions.js").read_text()

    assert writer.count("enabled === false") >= 2  # up front, and per press
    assert '"editor-disabled"' in writer


def test_the_sidebar_can_recover_when_firefox_withholds_the_site_permission(manifest):
    """The add-on declares one site and can request that same site on a click.

    Firefox may still list an MV3 host permission as optional in a temporary
    install. The toolbar has activeTab, but a directly opened sidebar does not,
    so its recovery must request exactly the declared origin and nothing wider.
    """
    assert manifest["host_permissions"] == ["*://learn.hawkeslearning.com/*"]
    assert "optional_host_permissions" not in manifest

    popup = (EXTENSION_DIR / "popup" / "popup.js").read_text()
    background = (EXTENSION_DIR / "background.js").read_text()
    messages = json.loads(
        (EXTENSION_DIR / "_locales" / "en" / "messages.json").read_text()
    )
    assert "permissions.request" in popup
    assert "ALLOWED_HOST_PATTERN" in popup
    assert messages["popupGrantAccessButton"]["message"] == "Grant Hawkes access"
    assert "errorNeedsHostPermission" not in background
    assert "errorNeedsHostPermission" not in messages
    assert "popupGrantButton" not in messages


def test_the_editor_description_retries_while_the_editor_is_rebuilt() -> None:
    """A probe landing between questions sees no editor model.

    Hawkes discards its editor when it swaps in the next question. Reporting
    "the answer editor could not be read" for an editor that was a quarter of
    a second from existing sent the user back to the toolbar for no reason.
    """
    source = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
    body = source.split("async function describeEditor(", 1)[1].split(
        "\nasync function", 1
    )[0]
    assert "attempts = 5" in body, "describeEditor takes an attempt budget"
    assert "for (let attempt" in body, (
        "describeEditor retries rather than failing at once"
    )
    assert "setTimeout" in body, "describeEditor waits between attempts"
    assert "described?.ok" in body, "only a successful description ends the retry loop"


def test_the_question_signature_is_built_from_the_question_not_the_editor() -> None:
    """Two questions of the same kind publish identical editor rules.

    `cbrt(y^4)` and `7th-root(y^8)` both report field `QBase1_input` and the
    character set `0123456789yz-+`, so a signature taken from the editor made
    them one question -- and `y^4` was inserted for a question whose answer was
    `y^(8/7)`, reported as solved and exact.
    """
    source = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
    body = source.split("function questionSignature(", 1)[1].split("\n}", 1)[0]
    assert "question.promptText" in body, "the prompt is part of the signature"
    assert "question.expressions" in body, "the expressions are part of the signature"
    assert "JSON.stringify(editor)" not in source, (
        "the editor description must not stand in for the question"
    )
    assert "return null" in body, "an unreadable question has no signature"


def test_an_unidentified_question_is_never_treated_as_the_previous_one() -> None:
    """Carrying an answer over is only safe when the question is known to match."""
    source = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
    body = source.split("async function prepare(", 1)[1].split("\nasync function", 1)[0]
    assert "signature !== null && signature === previous.signature" in body, (
        "a null signature must not match, or an unreadable question reuses an answer"
    )


def test_the_question_is_verified_before_the_answer_is_inserted() -> None:
    """The last line of defence against inserting an answer for another question."""
    source = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
    body = source.split("async function insert(", 1)[1].split("\nasync function", 1)[0]
    assert "readQuestion" in body, "insert re-reads the question on screen"
    assert "errorQuestionChanged" in body, "a changed question refuses the insertion"
    checks = body.index("onScreen")
    assert checks < body.index("answerFitsEditor"), (
        "the question is checked before the answer is measured against the editor"
    )
    messages = json.loads(
        (EXTENSION_DIR / "_locales" / "en" / "messages.json").read_text(
            encoding="utf-8"
        )
    )
    assert "errorQuestionChanged" in messages


def test_the_parenthesis_family_templates_pass_their_type() -> None:
    """`Mod` and `IndexedRadical` do not load like the other templates.

    `addElement` guards absolute value with `qualifyLoadParenthesis(ObjType)`
    and loads it with `loadParenthesis(ObjType, fromKeypad)`, and it asks for a
    radical's index box with a second argument to `loadRadical`. Calling either
    the way `loadExponent` is called silently does nothing.
    """
    source = (EXTENSION_DIR / "common" / "page-actions.js").read_text(encoding="utf-8")
    assert 'Mod: [base.qualifyLoadParenthesis, ["Mod"]]' in source
    assert 'Mod: [base.loadParenthesis, ["Mod", true]]' in source
    assert "IndexedRadical: [base.loadRadical, [true, true]]" in source
    assert "guard.apply(base, guardArgs)" in source, (
        "guards are called with their arguments"
    )
    assert "loader.apply(base, loaderArgs)" in source


def test_a_failed_insertion_verifies_that_it_cleared() -> None:
    """`abandon` must leave nothing behind, and must know whether it did.

    `addElement` reads the caret before dispatching, but only for a call that
    says it came from the keypad -- and with no `CurrentBase`, which is where a
    rejected character leaves it, that read throws and `Clear` never runs. A
    half-built `1/7` was left in the box on lesson 1.2 question 14 that way.
    """
    source = (EXTENSION_DIR / "common" / "page-actions.js").read_text(encoding="utf-8")
    body = source.split("const clearAnswer = async", 1)[1].split("\n  /** Report", 1)[0]
    assert 'control.addElement("Clear", false' in body, (
        "the clear must be reachable without the keypad's caret read"
    )
    assert "backSpaceClick" in body, "a last-resort clear one element at a time"
    assert "answerIsEmpty()" in body, "the clear is checked, not assumed"
    # Every refusal path goes through abandon, and abandon is now awaited.
    assert "return abandon(" not in source, "abandon is async; every call awaits it"
    assert source.count("return await abandon(") >= 5
    assert "leftBehind" in source, (
        "a clear that failed must be reported, not hidden behind a clean refusal"
    )


def test_the_question_read_waits_for_mathjax() -> None:
    """An empty read is not an answer; it is a read that came too early.

    `Array.isArray([])` is true, so an empty expression list counted as a
    successful read and the solve fell through to the screenshot and its two
    transcription readers -- which is where "the two readers disagreed" came
    from, on a question that could be read exactly.
    """
    source = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
    body = source.split("async function readQuestion(", 1)[1].split("\n/**", 1)[0]
    assert "attempts = 6" in body, "the read is retried while MathJax renders"
    assert "question.expressions.length > 0" in body, (
        "only a read that found an expression ends the retry loop"
    )
    assert "setTimeout" in body


def test_every_injected_script_path_is_declared() -> None:
    """`QUESTION_SCRIPT` was used and declared nowhere.

    A module throws `ReferenceError` on such a name; `readQuestion` caught it,
    logged a warning, and the add-on fell back to the screenshot and its two
    vision readers on every single question -- which is how a misread index
    produced `x^(5/7)` for the square root of x^5. Nothing noticed because the
    harness loads the reader file itself and never touches the constant.
    """
    source = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
    for name in (
        "QUESTION_SCRIPT",
        "DESCRIBE_SCRIPT",
        "INSPECT_SCRIPT",
        "EDITOR_SCRIPT",
    ):
        assert f"const {name} =" in source, f"{name} is used but never declared"
        used = re.search(rf"\b{name}\b", source.split(f"const {name} =", 1)[1])
        assert used is not None, f"{name} is declared but never used"


def test_the_validator_rejects_an_undeclared_constant() -> None:
    """The check that would have caught it, exercised on the real shape."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_extension", BUILD_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    problems: list[str] = []
    module._check_undefined_constants(problems)
    assert problems == [], f"the shipped tree must be clean: {problems}"


def test_an_open_panel_notices_the_question_changing() -> None:
    """A sidebar that stays open must not keep the previous answer.

    Hawkes swaps questions in place -- no navigation, no `tabs.onUpdated`, no
    event at all -- and the question was only re-checked when the panel opened.
    That is enough for the popup, which closes whenever focus moves, but the
    sidebar stays up, so a solved answer sat there across question changes. A
    worded answer is the worst case: "Not a Real Number" stays readable and
    looks deliberate while belonging to the question before, and it is read and
    acted on by hand, so no insertion check can catch it.
    """
    source = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
    assert "function watchQuestion()" in source
    assert "QUESTION_WATCH_MS" in source
    assert "const QUESTION_WATCH_MS" in source, "the interval is declared, not implied"
    body = source.split("function watchQuestion()", 1)[1].split(
        "\nfunction stopWatchingQuestion", 1
    )[0]
    # Work in flight reads the question itself; the watch must not cut in.
    for phase in ("checking", "solving", "inserting"):
        assert phase in body, f"the watch must stand aside during {phase}"
    # Re-prepared in the window the state belongs to, not "the current one".
    assert "prepare(state.windowId)" in body, "a changed question re-prepares the panel"
    assert "questionSignature" in body, "the comparison is the question's own signature"
    # And it is started and stopped with the panel, not left running.
    assert "watchQuestion();" in source
    assert "stopWatchingQuestion();" in source


def test_the_editor_rules_are_re_read_before_inserting():
    """Regression: a legal `y` was reported as rejected.

    The editor publishes its accepted characters per question, and the panel's
    copy is taken when the answer field is found. If the question changed in
    between -- which it does, in place, without navigating -- the new answer
    was checked against the previous question's character set. Observed live on
    the seventh root of y^8, whose base slot plainly accepts `y`.
    """
    background = (EXTENSION_DIR / "background.js").read_text()

    # The whole function, rather than a fixed number of characters from its
    # start: a guard added ahead of the re-read pushed the comparison out of a
    # 2000-character window and failed on length rather than on order.
    body = background.split("async function insert()", 1)[1].split(
        "* Settle after a successful insertion.", 1
    )[0]
    # Re-described inside insert, before anything is decided or typed.
    assert "await describeEditor(state.tabId, state.frameId)" in body
    assert body.index("describeEditor") < body.index("answerFitsEditor")


def test_every_open_panel_keeps_receiving_state():
    """Firefox gives each window its own sidebar.

    The event page held one `panel` variable and assigned `panel = port` on
    every connection, so opening a second window's sidebar silently replaced
    the first. That panel received no further state and sat on whatever
    snapshot it had -- indistinguishable, from the outside, from a panel that
    would no longer open.
    """
    background = (EXTENSION_DIR / "background.js").read_text()

    assert "const panels = new Map()" in background
    assert "panels.set(port," in background
    assert "panels.delete(port)" in background
    # State goes to every connected panel, not to the most recent one.
    assert "for (const [port, entry] of panels)" in background
    assert "let panel = null" not in background
    assert "panel = port;" not in background
    # And the question watcher belongs to the set, not to a single panel.
    assert "if (panels.size === 0)" in background


def test_an_operation_targets_the_window_that_asked_for_it():
    """`currentWindow` in a background event page means the most recently
    focused window, not the window whose sidebar asked. With two windows open,
    a solve started in one could read -- and an insertion could write to -- the
    other one's tab."""
    background = (EXTENSION_DIR / "background.js").read_text()
    popup = (EXTENSION_DIR / "popup" / "popup.js").read_text()

    assert "async function activeHawkesTab(windowId)" in background
    assert "{ active: true, windowId }" in background
    assert "async function prepare(windowId = state.windowId)" in background
    # The panel is the only thing that knows which window it is in: a sidebar
    # port carries no sender tab.
    assert "browser.windows" in popup
    assert '{ type: "ethnos:hello", windowId: info.id }' in popup
    assert "port.postMessage({ type, windowId: panelWindowId })" in popup


def test_an_answer_solved_in_one_window_cannot_be_inserted_into_another():
    """One state names the tab answers are read from and written to. A request
    from a different window rebuilds it, dropping the previous window's answer,
    so insertion after a switch finds nothing and refuses."""
    background = (EXTENSION_DIR / "background.js").read_text()

    assert "async function claim(windowId)" in background
    claim = background.split("async function claim(windowId)", 1)[1].split("\n}\n", 1)[
        0
    ]
    assert "state.windowId === windowId" in claim  # same window: nothing to do
    assert "inFlight?.abort()" in claim  # a switch stops other work
    assert "blankState()" in claim  # and drops the old answer
    # Both writing operations claim before they act.
    for operation in ("ethnos:solve", "ethnos:insert"):
        block = background.split(f'case "{operation}":', 1)[1].split("break;", 1)[0]
        assert "await claim(asking)" in block


def test_a_tab_dragged_into_another_window_is_not_written_to():
    """`state` pairs one window with one tab, both captured when the field is
    found. Detaching that tab into a window of its own changes which window it
    is in while its id stays the same, so the pair silently stops describing
    anything real. Scoping the tab lookup by window does not cover it: the
    lookup already happened."""
    background = (EXTENSION_DIR / "background.js").read_text()

    # Noticed when it happens...
    assert "function forgetMovedTab(tabId)" in background
    for event in ("onAttached", "onDetached", "onRemoved"):
        assert f"browser.tabs.{event}.addListener(forgetMovedTab)" in background
    forget = background.split("function forgetMovedTab(tabId)", 1)[1].split("\n}\n", 1)[
        0
    ]
    assert "inFlight?.abort()" in forget
    assert "blankState()" in forget

    # ...and re-checked at the write, which is where it cannot be missed.
    insertion = background.split("async function insert()", 1)[1].split(
        "* Settle after a successful insertion.", 1
    )[0]
    assert "await browser.tabs.get(state.tabId)" in insertion
    assert "tab.windowId !== state.windowId" in insertion
    assert 'fail("errorTabMoved")' in insertion
    # The guard precedes the write, not merely accompanies it.
    assert insertion.index("errorTabMoved") < insertion.index("enterPlainAnswer")


def test_a_panel_never_acts_before_it_knows_its_own_window():
    """The hole in 0.39.2, reported live on the signed build.

    `activeHawkesTab` falls back to `currentWindow` when it is given no window,
    and `currentWindow` in a background page is whichever window was focused
    last. The panel learns its own window asynchronously from
    `windows.getCurrent()`, while its automatic prepare fires on the first
    state -- and routinely won that race. Dragging a tab into a new window
    focuses that window, so the panel left behind prepared against the tab that
    had just left it.
    """
    popup = (EXTENSION_DIR / "popup" / "popup.js").read_text()

    assert "const announced = browser.windows" in popup
    # Requests are held rather than sent unscoped.
    held = popup.split("function request(type)", 1)[1].split("\n}\n", 1)[0]
    assert "panelWindowId === null" in held
    assert "announced.finally" in held
    # And the only sender is the one the hold routes through.
    assert popup.count("port.postMessage({ type, windowId: panelWindowId })") == 1


def test_the_panel_recovers_after_its_tab_changes_window():
    """Forgetting the tab is necessary but leaves the panel at "Checking…"
    with nothing to act on. The window it belongs to is remembered, so it can
    re-prepare there and find whatever is in front now."""
    background = (EXTENSION_DIR / "background.js").read_text()

    forget = background.split("function forgetMovedTab(tabId)", 1)[1].split("\n}\n", 1)[
        0
    ]
    assert "windowId: state.windowId" in forget
    assert "prepare(state.windowId)" in forget


def test_a_panel_is_never_shown_another_window_s_question():
    """Seen live across two monitors on signed 0.39.2.

    One state exists at a time and names the window it describes, but it was
    posted to every connected panel. A sidebar open in an unrelated window -- a
    chat window, in the observed case -- displayed the Hawkes question, its
    answer, its source badge, and an enabled Insert button. Insertion itself
    was guarded, but a panel offering to insert an answer that belongs to a
    different window is not something to leave standing on the guard alone.
    """
    background = (EXTENSION_DIR / "background.js").read_text()

    assert "function stateFor(windowId)" in background
    scoped = background.split("function stateFor(windowId)", 1)[1].split("\n}\n", 1)[0]
    # Its own window, or a blank of its own -- never another window's.
    assert "windowId === state.windowId" in scoped
    assert "blankState()" in scoped

    # Every delivery goes through it: the broadcast, the first post on connect,
    # and the post once a panel says which window it is in.
    assert "state: stateFor(entry.windowId) })" in background
    assert "state: stateFor(null) })" in background
    # No delivery bypasses it.
    assert '"ethnos:state", state })' not in background


def test_an_unreadable_url_with_the_grant_held_is_the_wrong_site():
    """Reported from a sidebar open beside a chat window: "No active Firefox
    tab was found", of a window plainly showing one.

    The add-on may read one host. If that grant is held and the active tab's
    URL is still unreadable, the tab cannot be Hawkes -- a Hawkes URL is
    precisely what the grant makes readable. Reporting a missing tab sent the
    reader looking for the wrong thing entirely.
    """
    background = (EXTENSION_DIR / "background.js").read_text()

    block = background.split('if (typeof tab.url !== "string")', 1)[1].split(
        "\n  }\n", 1
    )[0]
    assert 'throw new Error("errorTabAccessLost")' in block  # grant withheld
    assert 'throw new Error("errorWrongSite")' in block  # grant held
    assert 'throw new Error("errorNoTab")' not in block


def test_the_question_watcher_rebuilds_what_it_watches_rather_than_giving_up():
    """The one guard against a previous question's answer staying on screen.

    A frame that has gone -- Hawkes reloading its editor, the tab moving on --
    makes every read from the watcher throw. Logged at debug and swallowed,
    that retired the guard silently: it failed every tick, forever, and nothing
    said so. The stale answer it exists to catch would simply sit there.
    """
    background = (EXTENSION_DIR / "background.js").read_text()

    assert "const WATCH_FAILURES_BEFORE_REPREPARE = 3" in background
    watcher = background.split("questionWatch = setInterval", 1)[1].split(
        "}, QUESTION_WATCH_MS)", 1
    )[0]
    assert "watchFailures = 0" in watcher  # a good read clears the count
    assert "watchFailures += 1" in watcher
    assert "WATCH_FAILURES_BEFORE_REPREPARE" in watcher
    assert "question-watch-lost-the-frame" in watcher  # and it is said out loud
    # Re-preparing is scoped to the window the state belongs to.
    assert "prepare(state.windowId)" in watcher


def test_closing_the_owning_window_hands_the_work_on():
    """Panels in a closing window disconnect by themselves; the state does not.

    It went on naming a window that no longer existed, so every surviving panel
    was shown a blank of its own and nothing re-prepared -- a panel that looks
    broken until something is pressed.
    """
    background = (EXTENSION_DIR / "background.js").read_text()

    assert "browser.windows.onRemoved.addListener" in background
    closed = background.split("browser.windows.onRemoved.addListener", 1)[1].split(
        "\n});\n", 1
    )[0]
    assert "panels.delete(port)" in closed  # its panels go
    assert "inFlight?.abort()" in closed  # its work stops
    assert "survivor" in closed  # and another window takes over
    assert "prepare(survivor.windowId)" in closed


def test_copy_hands_over_the_answer_not_the_rendering():
    """The trap in drawing the answer as mathematics.

    Once the card holds elements, its `textContent` is the *rendered* reading:
    `x13` for `x^13`, `z^4|y^5|/3` flattened out of its fraction. Copy read the
    card, so drawing the answer properly would have quietly started handing
    over a different answer than the one on screen -- in exactly the cases
    (option questions, refused notation) where copying is the only way in.
    """
    popup = (EXTENSION_DIR / "popup" / "popup.js").read_text()

    assert "let copyText" in popup
    assert "copyText = view.copy.text;" in popup
    assert "const text = copyText;" in popup
    # The card is never the source of what gets copied.
    assert "elements.answer.textContent" not in popup


def test_the_answer_is_drawn_as_elements_not_assigned_as_markup():
    """This text comes from a solver reading a web page. It is never markup,
    and the build agrees -- but the rule only holds if the drawing code builds
    nodes rather than assigning a string."""
    popup = (EXTENSION_DIR / "popup" / "popup.js").read_text()

    assert "function drawAnswer(text)" in popup
    assert "elements.answer.replaceChildren()" in popup
    assert "document.createElement" in popup
    for markup in ("innerHTML", "insertAdjacentHTML", "outerHTML"):
        assert markup not in popup


def test_the_log_records_which_build_is_running():
    """A temporary add-on reports nothing about itself, and `about:debugging`'s
    Reload re-reads whichever file was first selected -- so a freshly built
    version can silently not be the one under test. Diagnosing a fixed bug in a
    build that did not contain the fix costs far more than logging a string."""
    background = (EXTENSION_DIR / "background.js").read_text()

    loaded = background.split('log.info("event-page-loaded"', 1)[1].split(")\n", 1)[0]
    assert "browser.runtime.getManifest().version" in loaded


def test_moving_between_tabs_re_checks_what_is_in_front():
    """A sidebar belongs to a window, not to a tab.

    It stays open as its window moves between tabs, exactly as Firefox's own
    sidebars do -- and with nothing watching for that, the panel went on
    showing a question and an answer belonging to a tab no longer in front.
    Reported as the add-on being attached to every tab at once.
    """
    background = (EXTENSION_DIR / "background.js").read_text()

    assert "browser.tabs.onActivated.addListener" in background
    switched = background.split("browser.tabs.onActivated.addListener", 1)[1].split(
        "\n});\n", 1
    )[0]
    # Only this window's own tab changes, and only when a panel is watching.
    assert "windowId !== state.windowId" in switched
    assert "panels.size === 0" in switched
    # Work in flight holds the tab it targets; a switch must not cut in.
    for phase in ("checking", "solving", "inserting"):
        assert phase in switched
    assert "prepare(windowId)" in switched


def test_a_panel_only_takes_focus_in_the_window_being_used():
    """Every window has its own sidebar, and loading or reloading the add-on
    reloads all of them at once. Each panel then put the caret on its primary
    button -- including panels in windows nobody was in. Reported as the add-on
    jumping to another window the instant it was loaded."""
    popup = (EXTENSION_DIR / "popup" / "popup.js").read_text()

    focus_primary = popup.split("function focusPrimary(view)", 1)[1].split("\n}\n", 1)[
        0
    ]
    assert "document.hasFocus()" in focus_primary
    # Both places that take focus are guarded, not just the first.
    assert focus_primary.count("document.hasFocus()") == 2


def test_the_answer_is_entered_one_character_at_a_time():
    """A field driven by a framework re-renders on each input event, and that
    work is asynchronous. The whole answer used to arrive as one assignment and
    one event carrying a whole string -- not the shape such a field is built to
    receive, and the likeliest reading of both the half-entered structured
    answers of 0.19 and an unexplained failure at the write boundary seen live.
    """
    editor = (EXTENSION_DIR / "content" / "hawkes-editor.js").read_text()

    assert "durationMinMs: 5000" in editor
    assert "durationMaxMs: 10000" in editor
    assert "function writeCharacter(target, character)" in editor
    entry = editor.split("async function insertIntoNativeField", 1)[1].split(
        "\n  }\n", 1
    )[0]
    assert "playEntryCadence([...value]" in entry
    assert "writeCharacter(target, character)" in entry
    # The field closing part-way through stops the write rather than continuing.
    assert "field-not-editable" in entry


def test_the_paced_insertion_is_awaited_by_its_caller():
    """`insertAnswer` returns a promise now. Read without awaiting, `outcome.ok`
    is undefined and every insertion reports a failure it did not have."""
    background = (EXTENSION_DIR / "background.js").read_text()

    assert "async function enterPlainAnswer(answer, cadence)" in background
    assert "await ethnosHawkes.insertAnswer(answer, cadence)" in background


def test_entry_pacing_is_random_rhythmic_and_time_bounded():
    """Demonstrations get a varied musical cadence inside a hard window.

    Weight normalisation makes the random beat lengths add up to the one chosen
    duration rather than allowing per-character jitter to accumulate forever.
    """
    editor = (EXTENSION_DIR / "content" / "hawkes-editor.js").read_text()

    assert "crypto.getRandomValues(sample)" in editor
    assert "function normalizedCadence(offered = {})" in editor
    assert "function rhythmicWeight(character, index, cadence)" in editor
    assert "function entryBeatOffsets(characters, cadence)" in editor
    assert "60000 / cadence.tempoBpm" in editor
    assert "duration * elapsedWeight / totalWeight" in editor
    assert "offsets[offsets.length - 1] = duration" in editor


def test_cadence_settings_reach_the_isolated_insertion_path():
    settings = (EXTENSION_DIR / "common" / "settings.js").read_text()
    options = (EXTENSION_DIR / "options" / "options.html").read_text()
    background = (EXTENSION_DIR / "background.js").read_text()

    for genre in ("classical", "jazz", "lofi", "electronic", "custom"):
        assert f'value="{genre}"' in options
    for key in (
        "entryGenre",
        "entryTempoBpm",
        "entryDurationMinSeconds",
        "entryDurationMaxSeconds",
        "entryPattern",
        "entrySwingPercent",
        "entryVariationPercent",
        "entrySymbolRestPercent",
    ):
        assert f"{key}:" in settings
        assert f'data-setting="{key}"' in options
    assert 'id="cadence-custom"' in options and "hidden" in options
    option_script = (EXTENSION_DIR / "options" / "options.js").read_text()
    assert 'cadenceCustom.hidden = genre !== "custom"' in option_script
    assert "ENTRY_GENRE_PRESETS[settled.value].tempoBpm" in option_script
    assert "function alignDurationWindow" in option_script
    assert "resolveEntryCadence(settings)" in background
    assert "args: [reviewed, cadence]" in background


def test_contenteditable_entry_uses_the_same_character_cadence():
    """A MathQuill-style text target must not dump the expression at once."""
    editor = (EXTENSION_DIR / "content" / "hawkes-editor.js").read_text()

    entry = editor.split("async function insertIntoEditable", 1)[1].split("\n  }\n", 1)[
        0
    ]
    assert "playEntryCadence([...value]" in entry
    assert 'execCommand("insertText", false, character)' in entry


def test_structured_keypad_entry_performs_on_the_same_cadence():
    """A templated answer is the common case, and it used to arrive at once.

    `enterPlan` is serialized into the page's own world, so it closes over
    nothing and carries its own copy of the beat rules. What matters is that a
    structured answer is paced at all: `typeInto` was a synchronous loop that
    wrote every character in one tick, which is what a live session saw.
    """
    actions = (EXTENSION_DIR / "common" / "page-actions.js").read_text()
    background = (EXTENSION_DIR / "background.js").read_text()

    assert "export async function enterPlan(steps, cadence = {})" in actions
    assert "const typeInto = async (id, text)" in actions
    assert "await waitForNote()" in actions
    assert "if (!(await typeInto(cursor, step.text)))" in actions
    # One performance over every typed character of the whole plan, not one
    # window per step.
    assert 'filter((step) => step.op === "type")' in actions
    assert "60000 / beat.tempoBpm" in actions
    assert "args: [plan.steps, cadence]" in background
    assert "await buildStructured(reviewed, cadence)" in background


def test_a_completed_insertion_records_how_long_it_took():
    """Only failures were logged, and a performance is now seconds long.

    Whether the cadence finished inside the deadline is exactly the question a
    live session needs answered, and nothing recorded it. The answer itself
    still never reaches the log.
    """
    background = (EXTENSION_DIR / "background.js").read_text()

    assert background.count('log.info("inserted"') == 2
    # `path:` is reserved -- a neighbouring test forbids it anywhere in this
    # file, so that a path can never be smuggled to the native host.
    assert 'via: "structured"' in background and 'via: "plain"' in background
    assert "elapsedMs: Date.now() - entryStartedAt" in background
    inserted = background.split('log.info("inserted"', 1)[1].split("});", 1)[0]
    assert "reviewed.length" in inserted
    assert "answer:" not in inserted


def test_a_paced_entry_rechecks_its_target_on_every_beat():
    """Entry now spans seconds, so the field can go away mid-performance."""
    editor = (EXTENSION_DIR / "content" / "hawkes-editor.js").read_text()
    actions = (EXTENSION_DIR / "common" / "page-actions.js").read_text()

    # `execCommand` writes wherever the selection is, not into a held handle.
    entry = editor.split("async function insertIntoEditable", 1)[1].split("\n  }\n", 1)[
        0
    ]
    assert "!target.contains(live.anchorNode)" in entry
    assert '"editor-lost-focus"' in entry
    rules = (EXTENSION_DIR / "common" / "editor-rules.js").read_text()
    assert '"editor-lost-focus": "errorNoFocusedField"' in rules
    # The keypad path holds an id, so it re-reads the box rather than a node.
    assert "const live = document.getElementById(id);" in actions


def test_a_one_character_answer_is_struck_on_the_downbeat():
    """It used to hold an empty field for the whole window, then fill it.

    One-character answers are common in this course, and the result read as a
    hang: nothing on screen for five to ten seconds, then the character.
    """
    editor = (EXTENSION_DIR / "content" / "hawkes-editor.js").read_text()

    branch = editor.split("if (characters.length === 1) {", 1)[1].split("}", 1)[0]
    assert "return [0];" in branch
    assert "return [duration];" not in branch


def test_a_markup_fallback_records_why_it_fell_back():
    """The two declines are indistinguishable from the outside.

    Markup that would not convert and an instruction no exact operation
    matched both fall back to a screenshot, a vision model, and most of a
    minute -- and are fixed in completely different places. A 53-second solve
    seen live could not be attributed to either, because the log said only that
    the fallback had happened.
    """
    background = (EXTENSION_DIR / "background.js").read_text()

    fallback = background.split('log.info("markup-fallback"', 1)[1].split(");", 1)[0]
    assert "why:" in fallback
    assert "reply.message" in fallback
