"""RC5: execute the conductor, writer and musical observer on a virtual clock."""

import json
import re
from pathlib import Path

import pytest

quickjs = pytest.importorskip("quickjs")
COMMON = Path(__file__).resolve().parents[1] / "extension" / "common"


def load(ctx, *names):
    for name in names:
        source = (COMMON / name).read_text()
        source = re.sub(r"^import\s[\s\S]*?;\s*$", "", source, flags=re.M)
        ctx.eval(re.sub(r"^export ", "", source, flags=re.M))


def value(ctx, expression):
    return json.loads(ctx.eval(f"JSON.stringify({expression})"))


@pytest.fixture
def clock():
    ctx = quickjs.Context()
    ctx.eval("""
      var now = 0, timers = [], writes = [], sounds = [], views = [];
      var performance = { now: () => now };
      var setTimeout = (fn, ms) => { const t = {fn, at: now + ms}; timers.push(t); return t; };
      var clearTimeout = t => { timers = timers.filter(item => item !== t); };
      var crypto = {randomUUID: () => 'bounded-test'};
      var completed = null;
    """)
    load(ctx, "cadence.js", "cadence-audio.js")
    return ctx


def pump(ctx, delay=0):
    for _ in range(20000):
        while ctx.execute_pending_job():
            pass
        if not ctx.eval("timers.length"):
            return
        ctx.eval(f"timers.sort((a,b) => a.at-b.at); var t = timers.shift(); now = Math.max(now,t.at) + {delay}; t.fn();")
    pytest.fail("conductor failed to terminate")


@pytest.mark.parametrize("seconds", range(2, 13))
@pytest.mark.parametrize("genre", ["classical", "jazz", "lofi", "electronic", "custom"])
def test_one_callback_drives_write_sound_and_view_at_identical_offsets(clock, seconds, genre):
    clock.eval(f"""
      var steps = [{{op:'type', text:'2x + 3/5^2, y'}}];
      var phrase = ethnosCadence.planSemanticPhrase(steps, {{durationMinMs:{seconds*1000}, durationMaxMs:{seconds*1000}}});
      ethnosCadence.playCharacters([...steps[0].text], (character,index) => {{
        writes.push([index, now]);
      }}, {{score:phrase}}, {{visit:(note,index) => {{
        const event = arrangeNote(note,index,{{genre:{json.dumps(genre)}}});
        sounds.push([index,now,event.offsetMs]); views.push([index,now]);
      }}}}).then(result => completed = result.failure === null);
    """)
    pump(clock)
    offsets = value(clock, "phrase.offsets")
    assert value(clock, "writes") == [[i, at] for i, at in enumerate(offsets)]
    assert value(clock, "views") == value(clock, "writes")
    assert value(clock, "sounds") == [[i, at, at] for i, at in enumerate(offsets)]
    assert offsets[-1] == seconds * 1000
    assert value(clock, "completed") is True


def test_event_loop_delay_does_not_accumulate_or_queue_a_second_audio_score(clock):
    clock.eval("""
      var phrase = ethnosCadence.planSemanticPhrase([{op:'type',text:'2x+3y-7'}], {durationMinMs:12000,durationMaxMs:12000});
      ethnosCadence.playCharacters([...'2x+3y-7'], (c,i) => writes.push([i,now]) && null,
        {score:phrase}, {visit:(n,i) => sounds.push([i,now])});
    """)
    pump(clock, delay=17)
    assert value(clock, "writes") == value(clock, "sounds")
    assert value(clock, "now") == 12017  # one lateness, not 17 ms per note


@pytest.mark.parametrize("audio_failure", ["throw", "pending"])
def test_audio_cannot_delay_refuse_or_extend_insertion(clock, audio_failure):
    observer = "throw new Error('device lost')" if audio_failure == "throw" else "return new Promise(() => {})"
    clock.eval(f"""
      ethnosCadence.playCharacters([...'123'], (c,i) => {{writes.push([i,now]);}},
        {{durationMinMs:2000,durationMaxMs:2000}}, {{visit:() => {{ {observer}; }}}})
        .then(result => completed = result.failure === null);
    """)
    pump(clock)
    assert value(clock, "completed") is True
    assert value(clock, "writes.length") == 3
    assert value(clock, "now") == 2000


def test_rejected_write_has_no_note_and_no_later_events(clock):
    clock.eval("""
      ethnosCadence.playCharacters([...'123'], (c,i) => i === 1 ? {code:'stale-target'} : null,
        {durationMinMs:2000,durationMaxMs:2000}, {visit:(n,i) => sounds.push(i)})
        .then(result => completed = result.failure.code);
    """)
    pump(clock)
    assert value(clock, "sounds") == [0]
    assert value(clock, "completed") == "stale-target"


def test_score_is_repeatable_and_arrangements_are_distinct_without_retiming(clock):
    clock.eval("""
      var steps = [{op:'template',name:'Fraction'},{op:'type',text:'2x+3'},
        {op:'slot',name:'denominator'},{op:'type',text:'5y'},
        {op:'template',name:'Exponent'},{op:'type',text:'2'}];
      var phrase = ethnosCadence.planSemanticPhrase(steps);
      var other = ethnosCadence.planSemanticPhrase(steps);
      var arrangements = ['classical','jazz','lofi','electronic','custom'].map(genre =>
        phrase.notes.map((note,i) => arrangeNote(note,i,{genre})));
    """)
    assert value(clock, "phrase") == value(clock, "other")
    arrangements = value(clock, "arrangements")
    assert len({json.dumps(a) for a in arrangements}) == 5
    for arrangement in arrangements:
        assert [note["offsetMs"] for note in arrangement] == value(clock, "phrase.offsets")
    notes = value(clock, "phrase.notes")
    assert notes[4]["slot"] == "denominator"
    assert notes[-1]["structures"] == ["Fraction", "Exponent"]
    assert notes[-1]["resolution"] is True


def test_whitespace_is_silent_and_structures_change_register_and_color(clock):
    clock.eval("""
      var plain = {character:'2',role:'number',offsetMs:300,structures:[]};
      var variants = [plain, {...plain,structures:['Exponent']},
        {...plain,structures:['Radical']}, {...plain,slot:'denominator'},
        {...plain,role:'rest'}, {...plain,resolution:true}]
        .map(note => arrangeNote(note,0,{genre:'classical'}));
    """)
    base, exponent, radical, denominator, rest, resolution = value(clock, "variants")
    assert exponent["pitches"][0] == base["pitches"][0] + 12
    assert denominator["pitches"][0] == base["pitches"][0] - 12
    assert radical["shimmer"] is True
    assert rest["pitches"] == []
    assert len(resolution["pitches"]) == 3


MAIN_FIXTURE = """
  var document = {
    querySelectorAll: selector => selector.includes('customMessageBox') ? [] : [box],
    getElementById: id => box && id === box.id ? box : null,
    dispatchEvent: event => { const [index, elapsed] = JSON.parse(event.detail); sounds.push([index,now,elapsed]); },
  };
  class HTMLInputElement {
    constructor() {this.id='answer'; this.held='';}
    get value() {return this.held;} set value(v) {this.held=v;}
    focus() {document.activeElement=this;}
    getBoundingClientRect() {return {width:100};}
    dispatchEvent(e) {writes.push([writes.length,now]);}
  }
  var box = new HTMLInputElement();
  var window = {quant_wp_UI:{controlsCollection:[{enabled:true}],focusedElementIndex:0}};
  class InputEvent { constructor(type, options) {Object.assign(this,options);} }
  class CustomEvent { constructor(type, options) {Object.assign(this,options);} }
"""


@pytest.mark.parametrize("seconds", [2, 6, 12])
def test_serialized_main_writer_consumes_the_shared_score_and_emits_in_its_write(clock, seconds):
    load(clock, "page-actions.js")
    clock.eval(MAIN_FIXTURE)
    clock.eval(f"""
      var steps = [{{op:'type',text:'2x+3'}}];
      var phrase = ethnosCadence.planSemanticPhrase(steps,{{durationMinMs:{seconds*1000},durationMaxMs:{seconds*1000}}});
      enterPlan(steps,{{score:phrase,channel:'test'}}).then(result => completed=result);
    """)
    pump(clock)
    assert value(clock, "completed.ok") is True
    assert value(clock, "writes") == [[i, t] for i, t in enumerate(value(clock, "phrase.offsets"))]
    assert [s[:2] for s in value(clock, "sounds")] == value(clock, "writes")


def test_suspended_or_missing_audio_device_never_queues_stale_notes(clock):
    clock.eval("""
      var instrument = new CadenceInstrument(() => {throw new Error('no device');});
      instrument.unlock();
      var audible = instrument.strike({character:'2',role:'number',offsetMs:0},0,{});
    """)
    assert value(clock, "audible") is False
    assert value(clock, "instrument.status()") == "unavailable"
    assert value(clock, "timers.length") == 0


def test_old_profile_retains_active_timing_until_atomic_apply(clock):
    clock.eval("""
      var LEVELS = ['info'];
      var stored = {entryGenre:'jazz',entryTempoBpm:100};
      var browser = {storage:{local:{get:async()=>stored,set:async p=>Object.assign(stored,p)}}};
    """)
    load(clock, "settings.js")
    clock.eval("readSettings().then(s => completed=s)")
    pump(clock)
    assert value(clock, "completed.entrySwingPercent") == 30

    assert value(clock, "completed.entryTempoBpm") == 100
    assert value(clock, "stored") == {"entryGenre": "jazz", "entryTempoBpm": 100}
    clock.eval("writeSettings({...completed,entryGenre:'electronic'}).then(()=>readSettings()).then(s=>completed=s)")
    pump(clock)
    assert value(clock, "stored.cadenceScoreVersion") == 1
    assert value(clock, "completed.entrySwingPercent") == 30


def test_presentation_port_is_bounded_to_its_run_tab_frame_and_order(clock):
    load(clock, "cadence-session.js")
    clock.eval("""
      var phrase=ethnosCadence.planSemanticPhrase([{op:'type',text:'123'}]);
      var current=true;
      var session=createCadencePresentation({tabId:7,frameId:2},phrase,{enabled:false},cue=>views.push(cue.index),()=>current);
      function port(frameId) {
        return {name:session.channel,sender:{tab:{id:7},frameId},
          onMessage:{addListener(fn){this.fn=fn;}},onDisconnect:{addListener(fn){this.fn=fn;}},
          postMessage(cue){this.sent=cue;},disconnect(){this.disconnected=true;}};
      }
      var wrong=port(3);attachCadencePort(wrong);
      var right=port(2);attachCadencePort(right);
      right.onMessage.fn({index:1,elapsedMs:100});
      right.onMessage.fn({index:0,elapsedMs:0});
      right.onMessage.fn({index:0,elapsedMs:0});
      current=false;right.onMessage.fn({index:1,elapsedMs:100});
    """)
    assert value(clock, "wrong.disconnected") is True
    assert value(clock, "views") == [0]
    clock.eval("session.close(false);right.onMessage.fn({index:1,elapsedMs:100})")
    assert value(clock, "views") == [0]
    assert value(clock, "right.sent.type") == "close"


def test_final_emitted_cue_can_drain_after_the_writer_returns_without_waiting(clock):
    load(clock, "cadence-session.js")
    clock.eval("""
      var phrase=ethnosCadence.planSemanticPhrase([{op:'type',text:'1'}]);
      var session=createCadencePresentation({tabId:7,frameId:0},phrase,{enabled:false},cue=>views.push(cue.index),()=>false);
      var port={name:session.channel,sender:{tab:{id:7},frameId:0},
        onMessage:{addListener(fn){this.fn=fn;}},onDisconnect:{addListener(fn){this.fn=fn;}},
        postMessage(){},disconnect(){}};
      attachCadencePort(port);
      session.close(true);
      port.onMessage.fn({index:0,elapsedMs:0});
    """)
    assert value(clock, "views") == [0]
    assert value(clock, "timers.length") == 0


FAKE_AUDIO = """
  var connections = 0;
  function audioNode() {
    const param={value:0,setTargetAtTime(){},setValueAtTime(){},
      linearRampToValueAtTime(){},exponentialRampToValueAtTime(){}};
    let connected=false;
    return {gain:param,frequency:param,threshold:param,knee:param,ratio:param,
      connect(){if(!connected){connections++;connected=true;}},
      disconnect(){if(connected){connections--;connected=false;}},start(){},stop(){}};
  }
  var device = {state:'suspended',currentTime:0,destination:{},
    createGain:audioNode,createDynamicsCompressor:audioNode,
    createBiquadFilter:audioNode,createOscillator:audioNode,
    resume:()=>new Promise(()=>{}),
    suspend(){this.state='suspended';return Promise.resolve();},
    close(){this.state='closed';connections=0;return Promise.resolve();}};
  var note={character:'2',role:'number',offsetMs:0};
"""


def test_first_note_survives_device_resume_and_denial_discards_queued_voices(clock):
    clock.eval(FAKE_AUDIO)
    clock.eval("""
      var instrument=new CadenceInstrument(()=>device);
      instrument.unlock();
      var queued=instrument.strike(note,0,{});
      var queuedVoices=instrument.voices.size;
      instrument.finish();
    """)
    assert value(clock, "queued") is True
    assert value(clock, "queuedVoices") > 0
    assert value(clock, "instrument.voices.size") == 0
    assert value(clock, "instrument.strike(note,0,{})") is False
    assert value(clock, "timers.length") == 0


def test_dense_burst_is_bounded_and_stop_closes_all_audio_resources(clock):
    clock.eval(FAKE_AUDIO)
    clock.eval("""
      var instrument=new CadenceInstrument(()=>device);
      instrument.unlock();device.state='running';
      for(let i=0;i<100;i++)instrument.strike(note,i,{});
      var peak=instrument.voices.size;
      instrument.close();
    """)
    assert value(clock, "peak") == 24
    assert value(clock, "instrument.voices.size") == 0
    assert value(clock, "device.state") == "closed"
    assert value(clock, "connections") == 0


def test_cancel_releases_observer_and_context_and_old_completion_cannot_stop_new_run(clock):
    load(clock, "cadence-session.js")
    clock.eval(FAKE_AUDIO)
    clock.eval("""
      insertionInstrument.contextFactory=()=>device;
      insertionInstrument.unlock();device.state='running';
      var phrase=ethnosCadence.planSemanticPhrase([{op:'type',text:'12'}]);
      var session=createCadencePresentation({tabId:7,frameId:0},phrase,{enabled:true},()=>{},()=>true);
      var port={name:session.channel,sender:{tab:{id:7},frameId:0},
        onMessage:{addListener(fn){this.fn=fn;}},onDisconnect:{addListener(fn){this.fn=fn;}},
        postMessage(cue){this.closed=cue.type==='close';},disconnect(){}};
      attachCadencePort(port);
      port.onMessage.fn({index:0,elapsedMs:0});
      cancelCadence();
      port.onMessage.fn({index:1,elapsedMs:100});
      var remaining=presentations.size;
      var closed=device.state;
      crypto.randomUUID=()=> 'new-run';
      insertionInstrument.unlock();device.state='running';
      var second=createCadencePresentation({tabId:7,frameId:0},phrase,{},()=>{},()=>true);
      insertionInstrument.strike(note,0,{});
      session.close(false);
    """)
    assert value(clock, "port.closed") is True
    assert value(clock, "remaining") == 0
    assert value(clock, "closed") == "closed"
    assert value(clock, "insertionInstrument.voices.size") > 0
    clock.eval("cancelCadence()")
    assert value(clock, "connections") == 0
