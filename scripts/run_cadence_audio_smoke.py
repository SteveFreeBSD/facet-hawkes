#!/usr/bin/env python3
"""Audible Cadence in real Firefox: Settings, actual Insert, and popup teardown.

Uses a throwaway profile and localhost fixtures. Only the origin and deterministic
solver result are substituted in the fixture copy; the actual panel Insert,
ownership checks, writers, score, audio and port lifecycle execute as shipped.
No coursework, models, credentials or existing Firefox profile are reached.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from harness.marionette import (
    Marionette,
    MarionetteError,
    action_button_selector,
    launch,
    pin_action_to_toolbar,
    widget_id,
)
from run_extension_harness import make_server
from run_settings_smoke import (
    ADDON_ID,
    EXTENSION_DIR,
    Settings,
    free_port,
    profile_prefs,
)


def async_js(m, source):
    return m.send(
        "WebDriver:ExecuteAsyncScript",
        {
            "script": "const done=arguments[arguments.length-1];"
            "(async()=>{" + source + "})().then(done,e=>done({error:String(e)}));",
            "args": [],
        },
    )["value"]


def raw(m, source):
    return m.execute(source)["value"]


def demand(condition, name, detail=None):
    if not condition:
        raise AssertionError(f"{name}: {detail}")
    print(
        f"ok   {name}" + (f" · {json.dumps(detail)}" if detail is not None else ""),
        flush=True,
    )


def eventually(fn, predicate, timeout=20):
    """Poll until the predicate holds, tolerating a view that is going away.

    Reading a popup or sidebar that Firefox is in the middle of destroying
    raises `Actor 'MarionetteCommands' destroyed ...`. That is the harness
    looking at the wrong instant, not a result, so it is retried like any other
    unsatisfied poll -- while a lasting failure still runs out the clock.
    """
    end = time.monotonic() + timeout
    result = None
    while time.monotonic() < end:
        try:
            result = fn()
        except MarionetteError as error:
            result = f"unavailable: {error}"
            time.sleep(0.1)
            continue
        if predicate(result):
            return result
        time.sleep(0.1)
    raise AssertionError(f"timed out: {result}")


AUDIO_HOOK = """
window.rc5Trace = [];
window.rc5Structures = [];
// Every device this page has ever opened. Settings should only ever want one.
window.rc5Contexts = new Set();
const rc5Original = previewInstrument.strike;
previewInstrument.strike = function(note,index,options) {
  const result = rc5Original.call(this,note,index,options);
  window.rc5Instrument = this;
  if (this.context) { window.rc5Contexts.add(this.context); }
  if (!window.rc5Analyser && this.context) {
    window.rc5Analyser = this.context.createAnalyser();
    this.master.connect(window.rc5Analyser);
  }
  window.rc5Trace.push({index,offset:note.offsetMs,played:result,at:performance.now()});
  return result;
};
const rc5Structure = previewInstrument.strikeStructure;
previewInstrument.strikeStructure = function(structure,options) {
  const result = rc5Structure.call(this,structure,options);
  window.rc5Structures.push({structure,played:result});
  return result;
};
"""


def settings_audio(m, artifact_dir):
    page = Settings(m)
    page.open_page()
    demand(
        page.evaluate("return Array.isArray(window.rc5Trace);") is True,
        "instrument Settings without replacing playback",
    )
    page.set_control("entryDurationMinSeconds", 2)
    page.set_control("entryDurationMaxSeconds", 2)
    traces = []
    for genre in ["classical", "jazz", "lofi", "electronic", "custom"]:
        page.set_control("entryGenre", genre)
        page.evaluate("window.rc5Trace=[]; return true;")
        page.click("#cadence-play")
        state = page.play_until(lambda state: state["stopHidden"])
        trace = page.evaluate("return window.rc5Trace;")
        demand(
            len(trace) == 11 and all(n["played"] for n in trace),
            f"{genre}: all eleven scheduled notes are audible",
            {"notes": len(trace), "played": sum(n["played"] for n in trace)},
        )
        demand(state["struck"] == 11, f"{genre}: visual score resolves with sound")
        traces.append([n["offset"] for n in trace])
    demand(
        all(trace == traces[0] for trace in traces),
        "all five genres share identical timestamps",
    )
    # Sample the real Web Audio graph, not merely AudioContext.state.
    page.click("#cadence-play")
    rms = page.evaluate("""
      const samples=new Float32Array(window.rc5Analyser.fftSize);
      window.rc5Analyser.getFloatTimeDomainData(samples);
      return Math.sqrt(samples.reduce((sum,v)=>sum+v*v,0)/samples.length);
    """)
    demand(rms > 0.00001, "real audio graph produces nonzero PCM", {"rms": rms})
    if artifact_dir:
        shot = m.send("WebDriver:TakeScreenshot", {})["value"]
        (artifact_dir / "settings-cadence.png").write_bytes(base64.b64decode(shot))
    page.click("#entryMusicMuted")
    demand(
        page.evaluate("return window.rc5Instrument.status();") == "muted",
        "mute takes effect during playback",
    )
    page.click("#cadence-stop")
    time.sleep(0.2)
    demand(
        page.evaluate("return window.rc5Instrument.voices.size;") == 0,
        "Stop releases every active voice",
    )
    page.click("#entryMusicMuted")
    page.click("#cadence-play")
    time.sleep(0.2)
    page.click("#cadence-play")
    state = page.play_until(lambda state: state["stopHidden"])
    demand(state["struck"] == 11, "restart replaces the performance")
    demand(
        page.evaluate("return window.rc5Contexts.size;") == 1,
        "eight previews, five arrangements and a restart share one output device",
        {"devices": page.evaluate("return window.rc5Contexts.size;")},
    )
    demand(
        [entry["structure"] for entry in page.evaluate("return window.rc5Structures;")][
            :3
        ]
        == ["Fraction", "Exponent", "Radical"],
        "the preview sounds the editor's own templates as they would land",
    )
    # The closing chord rings for as long as the arrangement gives it. What
    # matters is that the device is released once it has, not how soon.
    settled = eventually(
        lambda: page.evaluate(
            "const i=window.rc5Instrument;"
            "return {state:i.context?i.context.state:null, voices:i.voices.size};"
        ),
        lambda seen: seen and seen["state"] == "suspended",
        timeout=8,
    )
    demand(
        settled["voices"] == 0,
        "a finished phrase releases its voices and suspends the device it keeps",
        settled,
    )


FIXTURE = """<!doctype html><title>RC5 local insertion fixture</title>
<p>Simplify the following expression.</p>
<math xmlns="http://www.w3.org/1998/Math/MathML"><mrow><mn>2</mn><mi>x</mi><mo>+</mo><mn>3</mn></mrow></math>
<p>Answer</p><div id="editor"></div><button id="submit">Submit</button>
<script>
const mode = new URLSearchParams(location.search).get('mode');
const editor=document.querySelector('#editor');
const input=document.createElement(mode==='editable'?'div':'input');
input.id='txtAns1'; input.className='qbaseCSS'; input.dataset.slot='base';
if(mode==='editable'){input.contentEditable='true';input.setAttribute('role','textbox');}
editor.append(input); input.focus();
window.writes=[]; window.cues=[]; window.submitted=0;
document.addEventListener('rc5:observe',event=>{
 document.addEventListener(event.detail, cue=>window.cues.push({at:performance.timeOrigin+performance.now(),cue:JSON.parse(cue.detail)}));
});
document.querySelector('#submit').onclick=()=>window.submitted++;
editor.addEventListener('input', e=>window.writes.push({at:performance.timeOrigin+performance.now(),data:e.data}));
let serial=1;
const control={enabled:true,CurrentBase:{}, boxValue:()=>input.value||'',CurrentTextboxText:'',
  qdyBase_AllowedChar:'0123456789x+',qdyExpo_AllowedChar:'0123456789',qdyExpo_AllowedBaseChar:'0123456789x',
  qdyExponentAllowed:true,objMyDiv:editor,
  // Hawkes' own editor takes real time to load a template, and does not add
  // every box in one tick -- which is why the writer settles rather than
  // returning at the first change. The delays here are what make this a test
  // of that, and of the hold the phrase takes while it happens.
  keyPadButtonClick(name){
    // `keyPadButtonClick` delegates to `addElement`, which handles the
    // templates and special keys first and then falls through to an ordinary
    // character: it validates that character against the slot the editor is
    // in, writes it there and runs the editor's own change handler. A digit is
    // an editor operation here for the same reason `Exponent` is.
    if(name!=='Exponent'){
      const box=document.activeElement;
      if(!box||!box.classList||!box.classList.contains('qbaseCSS'))return;
      const allowed=box.dataset.slot==='exponent'
        ? control.qdyExpo_AllowedChar : control.qdyBase_AllowedChar;
      if(allowed.indexOf(name)<0)return;   // the editor's own refusal
      box.value=box.value+name;
      box.dispatchEvent(new InputEvent('input',{bubbles:true,data:name,inputType:'insertText'}));
      return;
    }
    const sup=document.createElement('sup'); const exponent=document.createElement('input');
    exponent.id='slot'+serial++;exponent.className='qbaseCSS';exponent.dataset.slot='exponent';sup.append(exponent);
    const continuation=document.createElement('input');continuation.id='slot'+serial++;continuation.className='qbaseCSS';continuation.dataset.slot='base';
    setTimeout(()=>{editor.append(sup);exponent.focus();},400);
    // Within `settle`'s stability window on purpose. It returns after three
    // quiet 60 ms polls, so an editor that paused longer than that between two
    // of its own boxes would be read as finished -- which fails closed, and is
    // tuned against the real editor rather than against this stub.
    setTimeout(()=>{editor.append(continuation);},480);
  }
};
if(mode==='structured')control.Type='Dynamic';
window.quant_wp_UI={focusedElementIndex:0,controlsCollection:[control],controlsCollectionData:[{
  isQDy:mode==='structured',boxValue:()=>'',validString:'[0-9x+]',Name:'Answer',enableState:true
}]};
</script>"""


def _check_parses(path):
    """Reject a patched script that JavaScript could not read."""
    import quickjs

    source = re.sub(r"^import\s[\s\S]*?;\s*$", "", path.read_text(), flags=re.M)
    source = re.sub(r"^export ", "", source, flags=re.M)
    try:
        quickjs.Context().eval("(function(){" + source + "})")
    except Exception as error:  # noqa: BLE001 - reported, not handled
        raise AssertionError(f"harness broke {path.name}: {error}") from error


def fixture_copy(directory, site, name="extension"):
    target = directory / name
    shutil.copytree(EXTENSION_DIR, target)
    for relative in ["content/hawkes-editor.js", "common/config.js", "background.js"]:
        path = target / relative
        source = path.read_text().replace(
            '"https://learn.hawkeslearning.com"', json.dumps(site)
        )
        # The sidebar, unlike the toolbar popup, cannot lean on `activeTab`: it
        # needs a granted host permission. Point that pattern at the fixture
        # too, so the grant below is the one the add-on actually checks for.
        source = source.replace(
            '"*://learn.hawkeslearning.com/*"', '"http://127.0.0.1/*"'
        )
        source = source.replace('"learn.hawkeslearning.com"', '"127.0.0.1"').replace(
            'url.protocol !== "https:"', 'url.protocol !== "http:"'
        )
        path.write_text(source)
    manifest = json.loads((target / "manifest.json").read_text())
    manifest["host_permissions"] = ["http://127.0.0.1/*"]
    (target / "manifest.json").write_text(json.dumps(manifest))
    session = target / "common/cadence-session.js"
    session.write_text(
        session.read_text().replace(
            "let next = 0;",
            "document.dispatchEvent(new CustomEvent('rc5:observe',{detail:channel})); let next = 0;",
        )
    )
    settings = target / "common/settings.js"
    settings.write_text(
        settings.read_text().replace(
            'autoSolve: { kind: "boolean", fallback: true }',
            'autoSolve: { kind: "boolean", fallback: false }',
        )
    )
    background = target / "background.js"
    background.write_text(
        background.read_text()
        + """
// Harness only: substitute the solved result, retaining every insertion guard.
globalThis.rc5Trace=[];
// A fresh id per evaluation of this module, which is what distinguishes an
// event page that was terminated and woken again from one that never stopped.
// `performance.timeOrigin` does not: it can survive the document that had it.
globalThis.rc5Generation=crypto.randomUUID();
globalThis.rc5SetGesture=json=>{globalThis.rc5Gesture=JSON.parse(json);};
const rc5Unlock=globalThis.facetCadenceUnlock;
globalThis.facetCadenceUnlock=()=>{
  globalThis.rc5Activation={active:navigator.userActivation?.isActive,at:Date.now()};
  return rc5Unlock();
};
const rc5Strike=insertionInstrument.strike.bind(insertionInstrument);
insertionInstrument.strike=(note,index,options)=>{
  const played=rc5Strike(note,index,options);
  globalThis.rc5Trace.push({index,offset:note.offsetMs,played,at:performance.timeOrigin+performance.now(),
    contextTime:insertionInstrument.context?.currentTime,contextState:insertionInstrument.context?.state,
    output:insertionInstrument.context?.getOutputTimestamp?.()});
  return played;
};
globalThis.rc5Seed=async()=>{
  if(state.phase!=='ready'||!state.signature)return;
  const tab=await browser.tabs.get(state.tabId);
  const answer=tab.url.includes('structured')?'x^2+3':'2x+3';
  globalThis.rc5Trace=[];
  update({phase:'solved',answer,entryText:answer,displayText:answer,source:'Local fixture'});
};
      globalThis.rc5Probe=async()=>{
        // Resolve the tab here rather than reading `state`: by this point the
        // lifecycle checks have deliberately navigated away, so the add-on has
        // correctly forgotten its target and there is nothing pinned.
        const [tab]=await browser.tabs.query({active:true,currentWindow:true});
        await browser.scripting.executeScript({target:{tabId:tab.id},func:()=>{
          globalThis.rc5SilentPort=browser.runtime.connect({name:'rc5-idle-probe'});
          rc5SilentPort.onDisconnect.addListener(()=>document.dispatchEvent(new CustomEvent('rc5:disconnected')));
        }});
        insertionInstrument.unlock();
        const ctx=insertionInstrument.context;
        await ctx.resume();
        const osc=ctx.createOscillator(),gain=ctx.createGain(); gain.gain.value=0.01;
        osc.connect(gain);gain.connect(ctx.destination);
        osc.start(ctx.currentTime);osc.stop(ctx.currentTime+60);
        globalThis.rc5ProbeStarted=Date.now();
        globalThis.rc5ProbeOsc=osc;
        return {start:rc5ProbeStarted,state:ctx.state,scheduledSeconds:60};
      };
// Every close of the output device, and who asked for it. An unexplained one
// would be a defect: the same call mid-answer would silence a performance.
globalThis.rc5Closes=[];
const rc5RealClose=insertionInstrument.close.bind(insertionInstrument);
insertionInstrument.close=()=>{
  globalThis.rc5Closes.push({at:Date.now(),by:String(new Error().stack).split(String.fromCharCode(10)).slice(1,4).join(' | ')});
  return rc5RealClose();
};
// Firefox announces an impending event-page suspension. Recording it separates
// "the page ended" from "the page was told it was ending and released audio".
globalThis.rc5Suspended=null;
browser.runtime.onSuspend?.addListener(()=>{globalThis.rc5Suspended=Date.now();});
// The exact listener that announcement is given, reachable from the observer.
// Firefox 155 has been seen announcing a suspension it did not carry out and
// announcing none at all, so the release is exercised rather than waited for.
globalThis.rc5Suspend=()=>{cancelCadence();return globalThis.rc5Report();};
globalThis.rc5AudioCost=async()=>{__AUDIO_COST__};
globalThis.rc5Cycle=async(rounds)=>{
  for(let round=0;round<rounds;round++){
    insertionInstrument.unlock();
    await new Promise(resolve=>setTimeout(resolve,20));
    insertionInstrument.strike({character:'2',role:'number',offsetMs:0,beat:0,accent:true},0,{genre:'lofi'});
    insertionInstrument.stop();
    insertionInstrument.close();
  }
  return rounds;
};
globalThis.rc5Report=()=>({phase:state.phase,error:state.errorKey,detail:state.detail,stage:state.stage,trace:globalThis.rc5Trace,
  audio:insertionInstrument.status(),voices:insertionInstrument.voices.size,
  contextState:insertionInstrument.context?.state??null,contextTime:insertionInstrument.context?.currentTime,
  measured:cadenceMeasurements(),
  generation:rc5Generation,suspended:globalThis.rc5Suspended,closes:globalThis.rc5Closes,
  activation:globalThis.rc5Activation,gesture:globalThis.rc5Gesture});
""".replace("__AUDIO_COST__", AUDIO_COST)
    )
    # This file is assembled by string replacement inside a Python literal, and
    # a stray escape once left an unterminated JavaScript string: `background.js`
    # then never evaluated at all, and every check downstream failed as though
    # the add-on were broken. Parse it here so a harness mistake says so.
    _check_parses(background)
    popup = target / "popup/popup.js"
    popup.write_text(
        popup.read_text()
        + """
window.rc5Visual=[];
document.addEventListener('click',event=>{
 if(event.target.closest('#insert')&&audioBackground)audioBackground.rc5SetGesture(JSON.stringify({trusted:event.isTrusted,active:navigator.userActivation.isActive}));
},true);
port.onMessage.addListener(incoming=>{
 if(incoming?.type==='ethnos:cadence')window.rc5Visual.push({...incoming.cue,at:performance.timeOrigin+performance.now()});
});
// Harness only: once production prepare has identified the fixture, seed its result.
port.onMessage.addListener(incoming=>{
  if(incoming?.type==='ethnos:state'&&incoming.state.phase==='ready') {
    browser.runtime.getBackgroundPage().then(bg=>bg.rc5Seed());
  }
});
"""
    )
    return target


def background_js(m, source="return window.rc5Report();"):
    # Inspect the existing remote context directly. Never getBackgroundPage(),
    # message the extension, or wake a stopped event page during observation.
    return raw(
        m,
        f"""
      const extension=WebExtensionPolicy.getByID({json.dumps(ADDON_ID)})?.extension;
      const actor=extension?.backgroundContext?.xulBrowser?.browsingContext?.currentWindowGlobal?.getActor('MarionetteCommands');
      return actor ? actor.executeScript({json.dumps(source)},[],{{timeout:5000,newSandbox:true}}) : {{stopped:true,state:extension?.backgroundState}};
    """,
    )


def popup_js(m, source):
    view = "PanelUI-webext-" + widget_id(ADDON_ID) + "-BAV"
    return raw(
        m,
        f"""
      const frame=document.getElementById({json.dumps(view)})?.querySelector('browser');
      const actor=frame?.browsingContext?.currentWindowGlobal?.getActor('MarionetteCommands');
      return actor ? actor.executeScript({json.dumps(source)}, [], {{timeout:5000,newSandbox:true}}) : null;
    """,
    )


def popup_click(m, selector):
    # Trusted native mouse input, through Firefox chrome into its remote popup.
    rect = popup_js(
        m,
        f"const r=document.querySelector({json.dumps(selector)}).getBoundingClientRect();return {{x:r.x+r.width/2,y:r.y+r.height/2}};",
    )
    view = "PanelUI-webext-" + widget_id(ADDON_ID) + "-BAV"
    point = raw(
        m,
        f"""
      const frame=document.getElementById({json.dumps(view)}).querySelector('browser');
      const r=frame.getBoundingClientRect();
      return {{x:Math.round(r.x+{rect["x"]}), y:Math.round(r.y+{rect["y"]})}};
    """,
    )
    return m.send(
        "WebDriver:PerformActions",
        {
            "actions": [
                {
                    "type": "pointer",
                    "id": "rc5-mouse",
                    "parameters": {"pointerType": "mouse"},
                    "actions": [
                        {
                            "type": "pointerMove",
                            "duration": 0,
                            "origin": "viewport",
                            **point,
                        },
                        {"type": "pointerDown", "button": 0},
                        {"type": "pointerUp", "button": 0},
                    ],
                }
            ]
        },
    )


SIDEBAR_ID = "-sidebar-action"


# The docked panel is not `#sidebar`: that element holds `webext-panels.xhtml`,
# and the add-on's own document is the `<browser>` inside it. Firefox names that
# view for us, which is steadier than walking the chrome DOM for it.
SIDEBAR_VIEW = f"""
  const extension = WebExtensionPolicy.getByID({json.dumps(ADDON_ID)})?.extension;
  const view = [...(extension?.views || [])].find(one => one.viewType === 'sidebar');
"""


def sidebar_js(m, source):
    return raw(
        m,
        SIDEBAR_VIEW
        + f"""
      const actor=view?.xulBrowser?.browsingContext?.currentWindowGlobal?.getActor('MarionetteCommands');
      return actor ? actor.executeScript({json.dumps(source)}, [], {{timeout:5000,newSandbox:true}}) : null;
    """,
    )


def sidebar_click(m, selector):
    """Trusted native input into the docked panel, as a hand would give it."""
    rect = sidebar_js(
        m,
        f"const r=document.querySelector({json.dumps(selector)}).getBoundingClientRect();return {{x:r.x+r.width/2,y:r.y+r.height/2}};",
    )
    # The inner browser fills its panel, so the panel's own position in the
    # chrome window is the whole of the offset.
    point = raw(
        m,
        f"""
      const r=document.getElementById('sidebar').getBoundingClientRect();
      return {{x:Math.round(r.x+{rect["x"]}), y:Math.round(r.y+{rect["y"]})}};
    """,
    )
    return m.send(
        "WebDriver:PerformActions",
        {
            "actions": [
                {
                    "type": "pointer",
                    "id": "rc5-mouse",
                    "parameters": {"pointerType": "mouse"},
                    "actions": [
                        {
                            "type": "pointerMove",
                            "duration": 0,
                            "origin": "viewport",
                            **point,
                        },
                        {"type": "pointerDown", "button": 0},
                        {"type": "pointerUp", "button": 0},
                    ],
                }
            ]
        },
    )


def press_insert(m, click, attempts=3):
    """Press Insert and wait until the answer is actually being entered.

    A synthetic pointer event into a panel that is still opening is delivered
    somewhere else, and the panel simply stays on the review screen. That is a
    harness problem, not the add-on's, so it is retried rather than reported:
    what the checks afterwards care about is a performance that has begun.
    """
    for attempt in range(attempts):
        click()
        for _ in range(40):
            report = background_js(m)
            if report.get("phase") in ("inserting", "inserted") or report.get("trace"):
                return report
            time.sleep(0.1)
        if attempt == attempts - 1:
            raise AssertionError(f"Insert never took: {report.get('phase')}")
    return report


def check_nothing_errored(m):
    """Read the add-on's own log, the way the Settings harness does.

    Every handler in the panel and the event page reports its failures there, so
    an error-level entry means something went wrong even when the visible state
    happened to settle. Without this the harness could only see what it thought
    to look at.
    """
    entries = background_js(
        m,
        "return (async()=>{const stored=await browser.storage.local.get('diagnostics');"
        "return (stored.diagnostics||[]).filter(entry=>entry.level==='error'"
        "||entry.level==='warn');})();",
    )
    errors = [entry for entry in (entries or []) if entry.get("level") == "error"]
    demand(
        not errors,
        "no error reached the add-on's own diagnostic log",
        {"errors": errors[:4], "warnings": len(entries or []) - len(errors)},
    )


def lifecycle_cases(m, site):
    """The endings: a page that leaves, and a panel that is docked rather than popped.

    Everything above ends a performance by finishing it. These are the two ways
    a real session ends one early, and both have to leave the same nothing
    behind -- no device, no voice, no port, and an insertion result that never
    depended on the sound in the first place.
    """
    command = widget_id(ADDON_ID) + SIDEBAR_ID
    # What "Always allow on this site" does, without a chrome doorhanger. The
    # toolbar popup gets by on `activeTab`; a docked sidebar outlives the click
    # that opened it, so the add-on requires a real grant and says so.
    granted = async_js(
        m,
        f"""
      const {{ExtensionPermissions}} = ChromeUtils.importESModule(
        'resource://gre/modules/ExtensionPermissions.sys.mjs');
      const policy = WebExtensionPolicy.getByID({json.dumps(ADDON_ID)});
      await ExtensionPermissions.add({json.dumps(ADDON_ID)},
        {{permissions: [], origins: ['http://127.0.0.1/*']}}, policy.extension);
      return [...policy.extension.allowedOrigins.patterns].map(one => one.pattern);
    """,
    )
    demand(
        "http://127.0.0.1/*" in granted,
        "the sidebar's host access is granted the way a user grants it",
        {"origins": granted},
    )
    background_js(
        m,
        "return browser.storage.local.set({entryDurationMinSeconds:12,entryDurationMaxSeconds:12});",
    )

    # Navigation, mid-phrase. The observer's own pagehide is what must close it.
    m.set_context("content")
    m.navigate(f"{site}/fixture.html?mode=native")
    time.sleep(0.4)
    m.set_context("chrome")
    m.click(action_button_selector(ADDON_ID))
    eventually(
        lambda: popup_js(
            m, "return {enabled:!document.querySelector('#insert').disabled};"
        ),
        lambda v: v and v["enabled"],
    )
    press_insert(m, lambda: popup_click(m, "#insert"))
    playing = eventually(
        lambda: background_js(m), lambda report: len(report.get("trace") or []) >= 1
    )
    demand(
        playing["contextState"] == "running",
        "a twelve-second phrase is under way before the page is taken away",
        {"struck": len(playing["trace"]), "state": playing["contextState"]},
    )
    m.set_context("content")
    m.navigate(f"{site}/fixture.html?mode=native")
    m.set_context("chrome")
    stopped = eventually(
        lambda: background_js(m),
        lambda report: report.get("contextState") is None,
        timeout=8,
    )
    demand(
        stopped["voices"] == 0,
        "navigating away closes the device and releases every voice mid-phrase",
        {
            "voices": stopped["voices"],
            "state": stopped["contextState"],
            "struck": len(stopped["trace"]),
        },
    )

    # The docked panel. Same background instrument, same score, no popup at all.
    background_js(
        m,
        "return browser.storage.local.set({entryDurationMinSeconds:2,entryDurationMaxSeconds:2});",
    )
    m.set_context("content")
    m.navigate(f"{site}/fixture.html?mode=native")
    time.sleep(0.6)
    m.set_context("chrome")
    raw(m, f"SidebarController.show({json.dumps(command)}); return true;")
    eventually(
        lambda: sidebar_js(m, "return !!document.querySelector('#insert');"),
        lambda value: value is True,
    )
    eventually(
        lambda: sidebar_js(
            m, "return {enabled:!document.querySelector('#insert').disabled};"
        ),
        lambda v: v and v["enabled"],
    )
    press_insert(m, lambda: sidebar_click(m, "#insert"))
    time.sleep(2.6)
    m.set_context("content")
    entered = raw(
        m,
        "return {text:[...document.querySelectorAll('#editor input')].map(n=>n.value).join(''),submitted:window.submitted};",
    )
    m.set_context("chrome")
    docked = background_js(m)
    demand(
        entered["text"] == "2x+3" and entered["submitted"] == 0,
        "the docked sidebar enters the answer and never submits",
        entered,
    )
    demand(
        len(docked["trace"]) == 4 and all(note["played"] for note in docked["trace"]),
        "the docked sidebar performs the same score with sound",
        {"notes": len(docked["trace"])},
    )
    progress = sidebar_js(
        m, "return document.querySelector('#insertion-score-status').textContent;"
    )
    demand(
        progress not in (None, ""),
        "the docked sidebar shows the score's own progress",
        {"status": progress},
    )

    # Closing and reopening the dock must not strand a port or a device.
    raw(m, "SidebarController.hide(); return true;")
    time.sleep(0.5)
    m.set_context("content")
    m.navigate(f"{site}/fixture.html?mode=native")
    time.sleep(0.6)
    m.set_context("chrome")
    raw(m, f"SidebarController.show({json.dumps(command)}); return true;")
    eventually(
        lambda: sidebar_js(m, "return !!document.querySelector('#insert');"),
        lambda value: value is True,
    )
    eventually(
        lambda: sidebar_js(
            m, "return {enabled:!document.querySelector('#insert').disabled};"
        ),
        lambda v: v and v["enabled"],
    )
    press_insert(m, lambda: sidebar_click(m, "#insert"))
    time.sleep(2.6)
    m.set_context("content")
    again = raw(
        m,
        "return [...document.querySelectorAll('#editor input')].map(n=>n.value).join('');",
    )
    m.set_context("chrome")
    reopened = background_js(m)
    demand(
        again == "2x+3" and len(reopened["trace"]) == 4,
        "a reopened sidebar performs again on a freshly opened device",
        {"text": again, "notes": len(reopened["trace"])},
    )
    settled = eventually(
        lambda: background_js(m),
        lambda report: report.get("contextState") is None,
        timeout=8,
    )
    demand(
        settled["voices"] == 0,
        "nothing is left holding a voice or a device",
        {"voices": settled["voices"]},
    )
    raw(m, "SidebarController.hide(); return true;")
    return settled


def insertion_audio(m, site):
    # Configure through the real storage schema in the fixture copy.
    m.set_context("content")
    page = Settings(m)
    page.open_page()
    async_js(
        m,
        "await browser.storage.local.set({autoSolve:false,entryMusicEnabled:true,entryMusicMuted:false,entryMusicVolume:30,entryDurationMinSeconds:2,entryDurationMaxSeconds:2,cadenceScoreVersion:1}); return true;",
    )
    m.set_context("chrome")
    pin_action_to_toolbar(m, ADDON_ID)
    # The sidebar opens automatically at install. Close it to exercise popup
    # teardown without another extension view or its question watcher.
    raw(m, "SidebarController.hide(); return true;")
    # The last pair is the same structured answer inside the shortest window the
    # schema allows: there, loading the template costs more time than the score
    # gave it, which is the case the fermata exists for.
    for mode, seconds in [
        ("native", 2),
        ("editable", 6),
        ("structured", 12),
        ("structured", 2),
    ]:
        background_js(
            m,
            f"return browser.storage.local.set({{entryDurationMinSeconds:{seconds},entryDurationMaxSeconds:{seconds}}});",
        )
        m.set_context("content")
        m.navigate(f"{site}/fixture.html?mode={mode}")
        time.sleep(0.4)
        m.set_context("chrome")
        m.click(action_button_selector(ADDON_ID))
        eventually(
            lambda: popup_js(
                m,
                "return {enabled:!document.querySelector('#insert').disabled,text:document.body.textContent};",
            ),
            lambda v: v and v["enabled"],
        )
        press_insert(m, lambda: popup_click(m, "#insert"))
        # Take the popup away once the phrase has demonstrably begun, so this
        # tests what it says it tests rather than whatever a fixed sleep caught.
        started = eventually(
            lambda: background_js(m), lambda report: len(report.get("trace") or []) >= 1
        )
        raw(
            m,
            "gBrowser.selectedBrowser.focus(); for(const panel of document.querySelectorAll('panel')){try{panel.hidePopup();}catch{}} return true;",
        )
        eventually(lambda: popup_js(m, "return true;"), lambda value: value is None)
        demand(True, f"{mode}: toolbar popup document destroyed mid-performance")
        during = background_js(m)
        # Either the phrase is still playing, or it already finished -- what the
        # popup's destruction must never do is stop it partway.
        demand(
            during.get("contextState") == "running" or len(during["trace"]) == 4,
            f"{mode}: the performance outlives the toolbar popup that started it",
            {
                "gesture": during["gesture"],
                "activation": during["activation"],
                "state": during["contextState"],
                "struck_when_closed": len(started["trace"]),
                "struck": len(during["trace"]),
            },
        )
        time.sleep(seconds + 0.1)
        m.set_context("content")
        result = raw(
            m,
            "return {text:[...document.querySelectorAll('#editor input')].map(n=>n.value).join('')||document.querySelector('#editor').textContent,writes:window.writes,cues:window.cues,submitted:window.submitted};",
        )
        m.set_context("chrome")
        report = background_js(m)
        demand(
            report["phase"] == "inserted",
            f"{mode}: insertion succeeds",
            {k: report[k] for k in ["phase", "error", "detail", "stage"]},
        )
        demand(
            result["text"] == ("x2+3" if mode == "structured" else "2x+3"),
            f"{mode}: actual Insert completes after popup closes",
            {"text": result["text"], "notes": len(result["writes"])},
        )
        demand(result["submitted"] == 0, f"{mode}: never submits")
        m.set_context("chrome")
        report = background_js(m)
        demand(
            len(report["trace"]) == len(result["writes"])
            and all(n["played"] for n in report["trace"]),
            f"{mode}: every inserted character emitted sound",
            {"notes": len(report["trace"]), "generation": report["generation"]},
        )
        lags = [
            round(note["at"] - write["at"], 2)
            for note, write in zip(report["trace"], result["writes"])
        ]
        demand(
            all(-3 <= lag < 150 for lag in lags),
            f"{mode}: bounded IPC delivery, no accumulating audio clock",
            {"latency_ms": lags},
        )
        # A four-part cue is a template landing, not a note: it holds the phrase
        # and never advances the counter, so it is not one of these.
        notes = [cue for cue in result["cues"] if len(cue["cue"]) == 2]
        structures = [cue for cue in result["cues"] if len(cue["cue"]) == 4]
        lateness = [
            round(cue["cue"][1] - note["offset"], 2)
            for cue, note in zip(notes, report["trace"])
        ]
        demand(
            max(lateness) < 400 and abs(lateness[-1] - lateness[0]) < 400,
            f"{mode}: no wake-up lateness accumulates across the phrase",
            {"insertion_lateness_ms": lateness, "drift_ms": lateness[-1] - lateness[0]},
        )
        held = [cue["cue"][3] for cue in structures]
        measured = report.get("measured") or {}
        print(
            {
                "mode": mode,
                "duration_s": seconds,
                "insertion_lateness_ms": lateness,
                "drift_ms": lateness[-1] - lateness[0],
                "structures": [c["cue"][2] for c in structures],
                "structural_hold_ms": held,
                "audio": measured,
            },
            flush=True,
        )
        if mode == "structured":
            demand(
                structures and structures[0]["cue"][2] == "Exponent",
                "the editor template announces itself as a held structure",
                {"structures": [c["cue"][2] for c in structures], "held_ms": held},
            )
        if mode == "structured" and seconds == 2:
            # The template really did overrun, and the notes after it still
            # arrived at the spacing the score gave them rather than at once.
            gaps = [round(b["cue"][1] - a["cue"][1]) for a, b in zip(notes, notes[1:])]
            demand(
                held[0] > 0 and min(gaps) > 50,
                "a template that overruns its slot holds the phrase instead of bursting it",
                {"held_ms": held[0], "gaps_ms": gaps},
            )
        demand(
            measured.get("holds")
            and max(measured["holds"]) <= 60
            and min(measured["holds"]) >= 8,
            f"{mode}: every voice is scheduled inside the perceptual lock",
            {
                k: measured.get(k)
                for k in (
                    "meanHoldMs",
                    "reanchors",
                    "baseLatencyMs",
                    "outputLatencyMs",
                    "maxLatenessMs",
                    "driftMs",
                )
            },
        )
    # The closing chord has a long natural release; what matters is that when it
    # is over nothing is left holding a voice or an output device.
    after = eventually(
        lambda: background_js(m),
        lambda report: report.get("contextState") is None,
        timeout=10,
    )
    demand(
        after["voices"] == 0,
        "a finished performance releases every voice and closes its device",
        {"voices": after["voices"], "contextState": after["contextState"]},
    )
    return after


TICKS = os.sysconf("SC_CLK_TCK")


def process_tree(pid):
    """Firefox and its children, because Web Audio does not run where you look."""
    found = [pid]
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(") ", 1)[1].split()
        except OSError:
            continue
        if int(fields[1]) in found:
            found.append(int(entry.name))
    return found


def cpu_and_memory(pid):
    """Total CPU seconds and resident memory across that tree, from /proc."""
    seconds = 0.0
    resident = 0
    for member in process_tree(pid):
        try:
            fields = (
                (Path("/proc") / str(member) / "stat")
                .read_text()
                .rsplit(") ", 1)[1]
                .split()
            )
            statm = (Path("/proc") / str(member) / "statm").read_text().split()
        except (OSError, IndexError):
            continue
        seconds += (int(fields[11]) + int(fields[12])) / TICKS
        resident += int(statm[1]) * 4096
    return seconds, resident


AUDIO_COST = """
  // Open a device from cold, and time how long until it is actually running.
  insertionInstrument.close();
  const started = performance.now();
  insertionInstrument.unlock();
  const opened = performance.now() - started;
  const deadline = started + 3000;
  while (insertionInstrument.context && insertionInstrument.context.state !== 'running'
         && performance.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 1));
  }
  const running = performance.now() - started;
  // Then the per-note cost of the arrangement itself, over a real score.
  const phrase = ethnosCadence.planSemanticPhrase(
    [{op:'template',name:'Fraction'},{op:'type',text:'2ix'},
     {op:'template',name:'Exponent'},{op:'type',text:'4'},{op:'base'},
     {op:'type',text:'+3'},{op:'slot',name:'denominator'},{op:'type',text:'5y'}], {});
  const costs = {};
  for (const genre of ['classical','jazz','lofi','electronic','custom']) {
    const from = performance.now();
    let rounds = 0;
    for (; rounds < 40; rounds++) {
      phrase.notes.forEach((note, index) => insertionInstrument.strike(note, index, {genre}));
      insertionInstrument.stop();
    }
    costs[genre] = Math.round(
      (performance.now() - from) * 1000 / (rounds * phrase.notes.length)) / 1000;
  }
  insertionInstrument.close();
  return {openMs: Math.round(opened * 100) / 100, runningMs: Math.round(running * 100) / 100,
    notes: phrase.notes.length, perNoteMs: costs};
"""


def performance_cost(m, site, pid):
    """What enabling the music actually costs, measured twice against itself.

    The same answer is entered twice into the same fixture, in the same browser,
    once with `entryMusicEnabled` off and once on. The difference is the whole
    cost of the feature: score, port, observer, arrangement, synthesis and
    output device. Everything else -- solving, ownership, the writer, the panel
    -- is in both halves and cancels.
    """
    m.set_context("chrome")
    pin_action_to_toolbar(m, ADDON_ID)
    raw(m, "SidebarController.hide(); return true;")
    background_js(
        m,
        "return browser.storage.local.set({autoSolve:false,entryMusicMuted:false,entryMusicVolume:30,cadenceScoreVersion:1});",
    )
    rows = {"silent": [], "music": []}
    # Three answers per arm, alternating, because one twelve-second answer is
    # well inside the noise of everything else a browser is doing.
    for _ in range(3):
        for enabled in (False, True):
            background_js(
                m,
                f"return browser.storage.local.set({{entryMusicEnabled:{str(enabled).lower()},entryDurationMinSeconds:12,entryDurationMaxSeconds:12}});",
            )
            m.set_context("content")
            m.navigate(f"{site}/fixture.html?mode=native")
            time.sleep(0.5)
            m.set_context("chrome")
            m.click(action_button_selector(ADDON_ID))
            eventually(
                lambda: popup_js(
                    m, "return {enabled:!document.querySelector('#insert').disabled};"
                ),
                lambda v: v and v["enabled"],
            )
            before = cpu_and_memory(pid)
            press_insert(m, lambda: popup_click(m, "#insert"))
            eventually(
                lambda: background_js(m),
                lambda report: report.get("phase") == "inserted",
                timeout=25,
            )
            after = cpu_and_memory(pid)
            raw(
                m,
                "for(const panel of document.querySelectorAll('panel')){try{panel.hidePopup();}catch{}} return true;",
            )
            rows["music" if enabled else "silent"].append(
                round(after[0] - before[0], 3)
            )
    mean = {arm: round(sum(values) / len(values), 3) for arm, values in rows.items()}
    cost = round(mean["music"] - mean["silent"], 3)
    demand(
        cost < 1.0,
        "the music costs a fraction of a core-second over a twelve-second answer",
        {
            "cpu_seconds": rows,
            "mean": mean,
            "extra_cpu_seconds": cost,
            "share_of_wall_clock": round(cost / 12, 4),
        },
    )
    audio = background_js(m, "return window.rc5AudioCost();")
    demand(
        audio.get("runningMs", 9999) < 250,
        "an output device opens well inside the observer's own setup budget",
        audio,
    )
    demand(
        max(audio["perNoteMs"].values()) < 2.0,
        "arranging and voicing one note costs a fraction of a millisecond",
        audio["perNoteMs"],
    )

    # Resident memory over one run is dominated by whatever the browser was
    # doing anyway. What is worth knowing is whether repeating the feature grows
    # it, so this opens and closes twenty devices between two collected points.
    def settled_resident():
        raw(m, "Cu.forceGC(); Cu.forceCC(); Cu.forceShrinkingGC(); return true;")
        time.sleep(1.0)
        return cpu_and_memory(pid)[1]

    before_devices = settled_resident()
    background_js(m, "return window.rc5Cycle(20);")
    growth = round((settled_resident() - before_devices) / 1e6, 2)
    demand(
        growth < 20,
        "twenty opened and closed devices do not accumulate resident memory",
        {"resident_growth_mb": growth, "devices": 20},
    )
    return {
        "insertion": rows,
        "audio": audio,
        "resident_growth_mb_over_20_devices": growth,
    }


def idle_lifecycle(m):
    # A deliberately silent runtime port and already-scheduled 40s oscillator
    # isolate idling from real score cues. This is a diagnostic, not playback.
    m.set_context("chrome")
    prefs = raw(
        m,
        """
      const prefs=Services.prefs;
      return Object.fromEntries(['extensions.background.idle.timeout','media.autoplay.default',
       'media.autoplay.allow-extension-background-pages','media.autoplay.block-webaudio'].map(name=>
       [name,{value:prefs.getPrefType(name)===0?null:prefs.getPrefType(name)===128?prefs.getBoolPref(name):prefs.getIntPref(name),overridden:prefs.prefHasUserValue(name)}]));
    """,
    )
    demand(
        not any(v["overridden"] for v in prefs.values()),
        "ordinary Firefox idle and autoplay preferences",
        prefs,
    )
    armed_generation = background_js(m).get("generation")
    armed = background_js(m, "return window.rc5Probe();")
    demand(
        armed and armed.get("state") == "running",
        "the idle probe really is holding an open port and a scheduled oscillator",
        armed,
    )
    # Then leave it completely alone. Polling the background page is itself
    # activity: an earlier version of this check asked every second, restarted
    # the page it had just let expire, and read the fresh one's empty state as
    # proof of nothing. So wait out the timeout without touching it, and ask
    # once. `generation` is stamped when the module is evaluated, so a page that
    # terminated and was woken by this very question still says so.
    idle_seconds = 60
    time.sleep(idle_seconds)
    after = background_js(m)
    ended = (
        bool(after.get("stopped"))
        or after.get("generation") != armed_generation
        # A woken page starts with an empty trace, whatever it says about itself.
        or not after.get("trace")
    )
    observed = {
        "idle_seconds": idle_seconds,
        "event_page_ended": ended,
        "suspend_announced": after.get("suspended") is not None,
        "audio_after": after.get("contextState"),
        "voices_after": after.get("voices"),
        "closes_during": [
            entry["by"]
            for entry in (after.get("closes") or [])
            if entry["at"] >= armed["start"]
        ],
    }
    # After a minute of nothing, the feature is holding no voice. That much is
    # its own doing and is asserted.
    demand(
        after.get("voices") == 0, "a minute of idling leaves no voice held", observed
    )
    # The device is a separate claim, and it is Firefox's to make: this probe
    # deliberately opened one and asked for a sixty-second oscillator, and the
    # only thing that releases it while the page lives is the suspension
    # announcement. Firefox 155 has been observed both announcing one it did not
    # carry out and announcing nothing at all, so *requiring* the device to be
    # gone here passed or failed on whether some earlier operation's `finish`
    # happened to land inside this window -- which is a fact about scheduling
    # and not about this feature. What is required is the release itself, so it
    # is exercised rather than waited for: `cancelCadence` is the exact listener
    # `runtime.onSuspend` is given, and calling it must leave nothing held.
    released = background_js(m, "return window.rc5Suspend();")
    observed["released_on_suspend"] = {
        "audio": released.get("contextState"),
        "voices": released.get("voices"),
    }
    demand(
        released.get("contextState") is None and released.get("voices") == 0,
        "the suspension handler releases every voice and closes the device",
        observed,
    )
    return {"prefs": prefs, "armed": armed, "after": after}


def run(show=False, artifacts=None, case="all"):
    with tempfile.TemporaryDirectory(prefix="rc5-audio-") as work:
        directory = Path(work)
        server_port = free_port()
        site = f"http://127.0.0.1:{server_port}"
        (directory / "fixture.html").write_text(FIXTURE)
        server = make_server(work, "127.0.0.1", server_port, {})

        def drive(addon, name, check):
            port = free_port()
            process = launch(
                str(directory / name),
                port,
                headless=not show,
                extra_prefs=profile_prefs(False),
            )
            m = Marionette(port=port)
            try:
                m.connect()
                m.new_session()
                m.install_addon(str(addon))
                m.set_context("content")
                check(m, process.pid)
            finally:
                if m.socket:
                    m.quit()
                process.terminate()
                process.wait(timeout=15)

        try:
            if case in ("all", "settings"):
                settings_copy = directory / "settings-extension"
                shutil.copytree(EXTENSION_DIR, settings_copy)
                options = settings_copy / "options/options.js"
                options.write_text(options.read_text() + AUDIO_HOOK)
                drive(
                    settings_copy,
                    "settings-profile",
                    lambda m, pid: settings_audio(m, artifacts),
                )
            if case in ("all", "insertion"):

                def insertion_checks(m, pid):
                    del pid
                    insertion_audio(m, site)
                    lifecycle_cases(m, site)
                    check_nothing_errored(m)
                    lifecycle = idle_lifecycle(m)
                    if artifacts:
                        (artifacts / "lifecycle.json").write_text(
                            json.dumps(lifecycle, indent=2)
                        )

                drive(
                    fixture_copy(directory, site), "insertion-profile", insertion_checks
                )
            if case in ("all", "performance"):
                # Its own browser: a CPU comparison has no business sharing one
                # with a lifecycle exercise that has deliberately left state
                # behind, and the two arms must differ only in the music.
                def performance_checks(m, pid):
                    cost = performance_cost(m, site, pid)
                    print(json.dumps({"performance": cost}, indent=2), flush=True)
                    if artifacts:
                        (artifacts / "performance.json").write_text(
                            json.dumps(cost, indent=2)
                        )

                drive(
                    fixture_copy(directory, site, "performance-extension"),
                    "performance-profile",
                    performance_checks,
                )
        finally:
            server.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument(
        "--case", choices=["all", "settings", "insertion", "performance"], default="all"
    )
    args = parser.parse_args()
    if args.artifacts:
        args.artifacts.mkdir(parents=True, exist_ok=True)
    run(args.show, args.artifacts, args.case)
