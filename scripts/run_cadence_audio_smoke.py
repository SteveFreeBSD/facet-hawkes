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
import shutil
import tempfile
import time
from pathlib import Path

from harness.marionette import (
    Marionette, action_button_selector, launch,
    pin_action_to_toolbar, widget_id,
)
from run_extension_harness import make_server
from run_settings_smoke import (
    ADDON_ID, ADDON_UUID, EXTENSION_DIR, Settings, free_port, profile_prefs,
)


def async_js(m, source):
    return m.send("WebDriver:ExecuteAsyncScript", {
        "script": "const done=arguments[arguments.length-1];"
        "(async()=>{" + source + "})().then(done,e=>done({error:String(e)}));",
        "args": [],
    })["value"]


def raw(m, source):
    return m.execute(source)["value"]


def demand(condition, name, detail=None):
    if not condition:
        raise AssertionError(f"{name}: {detail}")
    print(f"ok   {name}" + (f" · {json.dumps(detail)}" if detail is not None else ""), flush=True)


def eventually(fn, predicate, timeout=20):
    end = time.monotonic() + timeout
    result = None
    while time.monotonic() < end:
        result = fn()
        if predicate(result):
            return result
        time.sleep(0.1)
    raise AssertionError(f"timed out: {result}")


AUDIO_HOOK = """
window.rc5Trace = [];
const rc5Original = previewInstrument.strike;
previewInstrument.strike = function(note,index,options) {
  const result = rc5Original.call(this,note,index,options);
  window.rc5Instrument = this;
  if (!window.rc5Analyser && this.context) {
    window.rc5Analyser = this.context.createAnalyser();
    this.master.connect(window.rc5Analyser);
  }
  window.rc5Trace.push({index,offset:note.offsetMs,played:result,at:performance.now()});
  return result;
};
"""


def settings_audio(m, artifact_dir):
    page = Settings(m)
    page.open_page()
    demand(page.evaluate("return Array.isArray(window.rc5Trace);") is True, "instrument Settings without replacing playback")
    page.set_control("entryDurationMinSeconds", 2)
    page.set_control("entryDurationMaxSeconds", 2)
    traces = []
    for genre in ["classical", "jazz", "lofi", "electronic", "custom"]:
        page.set_control("entryGenre", genre)
        page.evaluate("window.rc5Trace=[]; return true;")
        page.click("#cadence-play")
        state = page.play_until(lambda state: state["stopHidden"])
        trace = page.evaluate("return window.rc5Trace;")
        demand(len(trace) == 11 and all(n["played"] for n in trace), f"{genre}: all eleven scheduled notes are audible", {"notes":len(trace),"played":sum(n["played"] for n in trace)})
        demand(state["struck"] == 11, f"{genre}: visual score resolves with sound")
        traces.append([n["offset"] for n in trace])
    demand(all(trace == traces[0] for trace in traces), "all five genres share identical timestamps")
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
    demand(page.evaluate("return window.rc5Instrument.status();") == "muted", "mute takes effect during playback")
    page.click("#cadence-stop")
    time.sleep(0.2)
    demand(page.evaluate("return window.rc5Instrument.voices.size;") == 0, "Stop releases every active voice")
    page.click("#entryMusicMuted")
    page.click("#cadence-play")
    time.sleep(0.2)
    page.click("#cadence-play")
    state = page.play_until(lambda state: state["stopHidden"])
    demand(state["struck"] == 11, "restart replaces the performance")
    time.sleep(1.7)
    demand(page.evaluate("return window.rc5Instrument.context.state;") == "suspended", "finished phrase suspends the audio device after its release")


FIXTURE = """<!doctype html><title>RC5 local insertion fixture</title>
<p>Simplify the following expression.</p>
<math xmlns="http://www.w3.org/1998/Math/MathML"><mrow><mn>2</mn><mi>x</mi><mo>+</mo><mn>3</mn></mrow></math>
<p>Answer</p><div id="editor"></div><button id="submit">Submit</button>
<script>
const mode = new URLSearchParams(location.search).get('mode');
const editor=document.querySelector('#editor');
const input=document.createElement(mode==='editable'?'div':'input');
input.id='txtAns1'; input.className='qbaseCSS';
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
  keyPadButtonClick(name){
    if(name==='Exponent'){
      const sup=document.createElement('sup'); const exponent=document.createElement('input');
      exponent.id='slot'+serial++;exponent.className='qbaseCSS';sup.append(exponent);editor.append(sup);
      const continuation=document.createElement('input');continuation.id='slot'+serial++;continuation.className='qbaseCSS';editor.append(continuation);
      exponent.focus();
    }
  }
};
if(mode==='structured')control.Type='Dynamic';
window.quant_wp_UI={focusedElementIndex:0,controlsCollection:[control],controlsCollectionData:[{
  isQDy:mode==='structured',boxValue:()=>'',validString:'[0-9x+]',Name:'Answer',enableState:true
}]};
</script>"""


def fixture_copy(directory, site):
    target = directory / "extension"
    shutil.copytree(EXTENSION_DIR, target)
    for relative in ["content/hawkes-editor.js", "common/config.js", "background.js"]:
        path = target / relative
        source = path.read_text().replace('"https://learn.hawkeslearning.com"', json.dumps(site))
        source = source.replace('"learn.hawkeslearning.com"', '"127.0.0.1"').replace('url.protocol !== "https:"', 'url.protocol !== "http:"')
        path.write_text(source)
    manifest = json.loads((target / "manifest.json").read_text())
    manifest["host_permissions"] = ["http://127.0.0.1/*"]
    (target / "manifest.json").write_text(json.dumps(manifest))
    session = target / "common/cadence-session.js"
    session.write_text(session.read_text().replace('let next = 0;', "document.dispatchEvent(new CustomEvent('rc5:observe',{detail:channel})); let next = 0;"))
    settings = target / "common/settings.js"
    settings.write_text(settings.read_text().replace('autoSolve: { kind: "boolean", fallback: true }', 'autoSolve: { kind: "boolean", fallback: false }'))
    background = target / "background.js"
    background.write_text(background.read_text() + """
// Harness only: substitute the solved result, retaining every insertion guard.
globalThis.rc5Trace=[];
globalThis.rc5Generation=performance.timeOrigin;
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
        await browser.scripting.executeScript({target:{tabId:state.tabId},func:()=>{
          globalThis.rc5SilentPort=browser.runtime.connect({name:'rc5-idle-probe'});
          rc5SilentPort.onDisconnect.addListener(()=>document.dispatchEvent(new CustomEvent('rc5:disconnected')));
        }});
        insertionInstrument.unlock();
        const ctx=insertionInstrument.context;
        await ctx.resume();
        const osc=ctx.createOscillator(),gain=ctx.createGain(); gain.gain.value=0.01;
        osc.connect(gain);gain.connect(ctx.destination);
        osc.start(ctx.currentTime);osc.stop(ctx.currentTime+40);
        globalThis.rc5ProbeStarted=Date.now();
        globalThis.rc5ProbeOsc=osc;
        return {start:rc5ProbeStarted,state:ctx.state};
      };
globalThis.rc5Report=()=>({phase:state.phase,error:state.errorKey,trace:globalThis.rc5Trace,
  audio:insertionInstrument.status(),voices:insertionInstrument.voices.size,
  contextState:insertionInstrument.context?.state,contextTime:insertionInstrument.context?.currentTime,
  generation:rc5Generation,activation:globalThis.rc5Activation,gesture:globalThis.rc5Gesture});
""")
    popup = target / "popup/popup.js"
    popup.write_text(popup.read_text() + """
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
""")
    return target


def background_js(m, source="return window.rc5Report();"):
    # Inspect the existing remote context directly. Never getBackgroundPage(),
    # message the extension, or wake a stopped event page during observation.
    return raw(m, f"""
      const extension=WebExtensionPolicy.getByID({json.dumps(ADDON_ID)})?.extension;
      const actor=extension?.backgroundContext?.xulBrowser?.browsingContext?.currentWindowGlobal?.getActor('MarionetteCommands');
      return actor ? actor.executeScript({json.dumps(source)},[],{{timeout:5000,newSandbox:true}}) : {{stopped:true,state:extension?.backgroundState}};
    """)


def popup_js(m, source):
    view = "PanelUI-webext-" + widget_id(ADDON_ID) + "-BAV"
    return raw(m, f"""
      const frame=document.getElementById({json.dumps(view)})?.querySelector('browser');
      const actor=frame?.browsingContext?.currentWindowGlobal?.getActor('MarionetteCommands');
      return actor ? actor.executeScript({json.dumps(source)}, [], {{timeout:5000,newSandbox:true}}) : null;
    """)


def popup_click(m, selector):
    # Trusted native mouse input, through Firefox chrome into its remote popup.
    rect = popup_js(m, f"const r=document.querySelector({json.dumps(selector)}).getBoundingClientRect();return {{x:r.x+r.width/2,y:r.y+r.height/2}};")
    view = "PanelUI-webext-" + widget_id(ADDON_ID) + "-BAV"
    point = raw(m, f"""
      const frame=document.getElementById({json.dumps(view)}).querySelector('browser');
      const r=frame.getBoundingClientRect();
      return {{x:Math.round(r.x+{rect['x']}), y:Math.round(r.y+{rect['y']})}};
    """)
    return m.send("WebDriver:PerformActions", {"actions":[{
        "type":"pointer", "id":"rc5-mouse", "parameters":{"pointerType":"mouse"},
        "actions":[{"type":"pointerMove","duration":0,"origin":"viewport",**point},
                   {"type":"pointerDown","button":0}, {"type":"pointerUp","button":0}]
    }]})



def insertion_audio(m, site):
    # Configure through the real storage schema in the fixture copy.
    m.set_context("content")
    page = Settings(m)
    page.open_page()
    async_js(m, "await browser.storage.local.set({autoSolve:false,entryMusicEnabled:true,entryMusicMuted:false,entryMusicVolume:30,entryDurationMinSeconds:2,entryDurationMaxSeconds:2,cadenceScoreVersion:1}); return true;")
    m.set_context("chrome")
    pin_action_to_toolbar(m, ADDON_ID)
    # The sidebar opens automatically at install. Close it to exercise popup
    # teardown without another extension view or its question watcher.
    raw(m, "SidebarController.hide(); return true;")
    for mode, seconds in [("native",2), ("editable",6), ("structured",12)]:
        background_js(m, f"return browser.storage.local.set({{entryDurationMinSeconds:{seconds},entryDurationMaxSeconds:{seconds}}});")
        m.set_context("content")
        m.navigate(f"{site}/fixture.html?mode={mode}")
        time.sleep(0.4)
        m.set_context("chrome")
        m.click(action_button_selector(ADDON_ID))
        eventually(lambda: popup_js(m, "return {enabled:!document.querySelector('#insert').disabled,text:document.body.textContent};"), lambda v:v and v['enabled'])
        popup_click(m, "#insert")
        time.sleep(0.4)
        raw(m, "gBrowser.selectedBrowser.focus(); for(const panel of document.querySelectorAll('panel')){try{panel.hidePopup();}catch{}} return true;")
        eventually(lambda: popup_js(m, "return true;"), lambda value:value is None)
        demand(True, f"{mode}: toolbar popup document destroyed during insertion")
        during=background_js(m)
        demand(during.get('contextState')=='running', f"{mode}: AudioContext survives popup destruction", {"gesture":during["gesture"],"activation":during["activation"],"state":during["contextState"]})
        time.sleep(seconds+0.1)
        m.set_context("content")
        result = raw(m, "return {text:[...document.querySelectorAll('#editor input')].map(n=>n.value).join('')||document.querySelector('#editor').textContent,writes:window.writes,cues:window.cues,submitted:window.submitted};")
        m.set_context("chrome")
        report = background_js(m)
        demand(report['phase']=='inserted', f"{mode}: insertion succeeds", {k:report[k] for k in ['phase','error']})
        demand(result["text"] == ("x2+3" if mode == "structured" else "2x+3"), f"{mode}: actual Insert completes after popup closes", {"text":result["text"],"notes":len(result["writes"])})
        demand(result["submitted"] == 0, f"{mode}: never submits")
        m.set_context("chrome")
        report = background_js(m)
        demand(len(report["trace"]) == len(result["writes"]) and all(n["played"] for n in report["trace"]), f"{mode}: every inserted character emitted sound", {"notes":len(report["trace"]),"generation":report["generation"]})
        lags = [round(note["at"] - write["at"], 2) for note, write in zip(report["trace"], result["writes"])]
        demand(all(-3 <= lag < 150 for lag in lags), f"{mode}: bounded IPC delivery, no accumulating audio clock", {"latency_ms": lags})
        lateness=[round(cue['cue'][1]-note['offset'],2) for cue,note in zip(result['cues'],report['trace'])]
        print({'mode':mode,'duration_s':seconds,'insertion_lateness_ms':lateness,'drift_ms':lateness[-1]-lateness[0]},flush=True)
    time.sleep(1.7)
    after=background_js(m)
    demand(after['voices']==0 and after['contextState']=='suspended', 'consecutive performances release all voices and suspend one reused context')
    return after


def idle_lifecycle(m):
    # A deliberately silent runtime port and already-scheduled 40s oscillator
    # isolate idling from real score cues. This is a diagnostic, not playback.
    m.set_context('chrome')
    prefs=raw(m, """
      const prefs=Services.prefs;
      return Object.fromEntries(['extensions.background.idle.timeout','media.autoplay.default',
       'media.autoplay.allow-extension-background-pages','media.autoplay.block-webaudio'].map(name=>
       [name,{value:prefs.getPrefType(name)===0?null:prefs.getPrefType(name)===128?prefs.getBoolPref(name):prefs.getIntPref(name),overridden:prefs.prefHasUserValue(name)}]));
    """)
    demand(not any(v['overridden'] for v in prefs.values()), 'ordinary Firefox idle and autoplay preferences', prefs)
    background_js(m, "return window.rc5Probe();")
    started=time.monotonic(); history=[]
    while time.monotonic()-started < 34:
        report=background_js(m)
        history.append({'elapsed':round(time.monotonic()-started,2),**report})
        if report.get('stopped'):break
        time.sleep(1)
    demand(history[-1].get('stopped'), 'silent port and scheduled Web Audio do not prevent natural event-page shutdown',
      {'alive_until_s':history[-2]['elapsed'],'stopped_by_s':history[-1]['elapsed'],'last_audio_state':history[-2]['contextState']})
    return {'prefs':prefs,'history':history}


def run(show=False, artifacts=None, case="all"):
    with tempfile.TemporaryDirectory(prefix="rc5-audio-") as work:
        directory = Path(work)
        server_port = free_port()
        site = f"http://127.0.0.1:{server_port}"
        (directory / "fixture.html").write_text(FIXTURE)
        server = make_server(work, "127.0.0.1", server_port, {})

        def drive(addon, name, check):
            port = free_port()
            process = launch(str(directory / name), port, headless=not show,
                extra_prefs=profile_prefs(False))
            m = Marionette(port=port)
            try:
                m.connect()
                m.new_session()
                m.install_addon(str(addon))
                m.set_context("content")
                check(m)
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
                drive(settings_copy, "settings-profile", lambda m: settings_audio(m, artifacts))
            if case in ("all", "insertion"):
                def insertion_checks(m):
                    insertion_audio(m, site)
                    lifecycle=idle_lifecycle(m)
                    if artifacts:(artifacts/'lifecycle.json').write_text(json.dumps(lifecycle,indent=2))
                drive(fixture_copy(directory, site), "insertion-profile", insertion_checks)
        finally:
            server.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--case", choices=["all", "settings", "insertion"], default="all")
    args = parser.parse_args()
    if args.artifacts:
        args.artifacts.mkdir(parents=True, exist_ok=True)
    run(args.show, args.artifacts, args.case)
