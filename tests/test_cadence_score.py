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
        ctx.eval(
            f"timers.sort((a,b) => a.at-b.at); var t = timers.shift(); now = Math.max(now,t.at) + {delay}; t.fn();"
        )
    pytest.fail("conductor failed to terminate")


@pytest.mark.parametrize("seconds", range(2, 13))
@pytest.mark.parametrize("genre", ["classical", "jazz", "lofi", "electronic", "custom"])
def test_one_callback_drives_write_sound_and_view_at_identical_offsets(
    clock, seconds, genre
):
    clock.eval(f"""
      var steps = [{{op:'type', text:'2x + 3/5^2, y'}}];
      var phrase = ethnosCadence.planSemanticPhrase(steps, {{durationMinMs:{seconds * 1000}, durationMaxMs:{seconds * 1000}}});
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
    observer = (
        "throw new Error('device lost')"
        if audio_failure == "throw"
        else "return new Promise(() => {})"
    )
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
        assert [note["offsetMs"] for note in arrangement] == value(
            clock, "phrase.offsets"
        )
    notes = value(clock, "phrase.notes")
    assert notes[4]["slot"] == "denominator"
    assert notes[-1]["structures"] == ["Fraction", "Exponent"]
    assert notes[-1]["resolution"] is True


def melody(voiced):
    """The character's own voice, which always carries the exact score offset."""
    return next(layer for layer in voiced["layers"] if layer["kind"] == "melody")


def kinds(voiced):
    return [layer["kind"] for layer in voiced["layers"]]


def test_whitespace_is_silent_and_structures_change_register_and_color(clock):
    clock.eval("""
      var plain = {character:'2',role:'number',offsetMs:300,structures:[],beat:0};
      var variants = [plain, {...plain,structures:['Exponent']},
        {...plain,structures:['Radical']}, {...plain,slot:'denominator'},
        {...plain,role:'rest'}, {...plain,resolution:true}]
        .map(note => arrangeNote(note,0,{genre:'classical'}));
    """)
    base, exponent, radical, denominator, rest, resolution = value(clock, "variants")
    assert melody(exponent)["midi"] == melody(base)["midi"] + 12
    assert melody(denominator)["midi"] == melody(base)["midi"] - 12
    assert melody(exponent)["color"] > melody(base)["color"]
    assert melody(denominator)["color"] < melody(base)["color"]
    # A radical rings an extra upper partial; nothing else about it changes.
    assert len(melody(radical)["partials"]) == len(melody(base)["partials"]) + 1
    assert rest["layers"] == []
    # The last character carries the arrangement's own closing chord.
    assert kinds(resolution).count("chord") == 4


def test_the_expression_itself_moves_the_harmony_and_resolves_the_phrase(clock):
    clock.eval("""
      var phrase = ethnosCadence.planSemanticPhrase([{op:'type',text:'2x+3y-7'}]);
      var harmony = phrase.notes.map(note => note.harmony);
      var voiced = phrase.notes.map((note,i) => arrangeNote(note,i,{genre:'classical'}));
    """)
    # `2x+3y-7`: the two operators are the only places the chord turns.
    assert value(clock, "harmony") == [0, 0, 0, 1, 1, 1, 2]
    voiced = value(clock, "voiced")
    # Chords appear on the operators and on the closing two notes, nowhere else.
    assert [index for index, note in enumerate(voiced) if "chord" in kinds(note)] == [
        2,
        5,
        6,
    ]
    assert (
        len(
            {
                tuple(
                    layer["midi"]
                    for layer in note["layers"]
                    if layer["kind"] == "chord"
                )
                for note in voiced
                if "chord" in kinds(note)
            }
        )
        == 3
    )


def test_a_variable_keeps_one_pitch_wherever_it_appears(clock):
    clock.eval("""
      var phrase = ethnosCadence.planSemanticPhrase([{op:'type',text:'x+2x+3x'}]);
      var voiced = phrase.notes.map((note,i) => arrangeNote(note,i,{genre:'jazz'}));
    """)
    voiced = value(clock, "voiced")
    variables = [
        melody(note)["midi"] for index, note in enumerate(voiced) if index in (0, 3, 6)
    ]
    assert len(set(variables)) == 1


def test_a_template_landing_sounds_without_becoming_a_scored_note(clock):
    clock.eval("""
      var fraction = arrangeStructure('Fraction',{genre:'classical'});
      var exponent = arrangeStructure('Exponent',{genre:'classical'});
    """)
    fraction = value(clock, "fraction")
    exponent = value(clock, "exponent")
    assert "offsetMs" not in fraction
    assert {layer["kind"] for layer in fraction["layers"]} == {"structure"}
    # A fraction opens below the phrase; an exponent opens above it.
    assert fraction["layers"][0]["midi"] < exponent["layers"][0]["midi"]


#: One plain Hawkes answer box: no page-owned character API, so its own
#: `input` handling is the native path and the write is the prototype setter.
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
    // Only the write itself is a write. `beforeinput` is the box's own
    // preflight and is answered, not counted.
    dispatchEvent(e) {
      if (e.type === 'input') { writes.push([writes.length,now]); }
      return true;
    }
  }
  var box = new HTMLInputElement();
  var window = {quant_wp_UI:{controlsCollection:[{enabled:true}],focusedElementIndex:0}};
  class InputEvent { constructor(type, options) {this.type=type; Object.assign(this,options);} }
  class CustomEvent { constructor(type, options) {this.type=type; Object.assign(this,options);} }
"""


@pytest.mark.parametrize("seconds", [2, 6, 12])
def test_serialized_main_writer_consumes_the_shared_score_and_emits_in_its_write(
    clock, seconds
):
    load(clock, "page-actions.js")
    clock.eval(MAIN_FIXTURE)
    clock.eval(f"""
      var steps = [{{op:'type',text:'2x+3'}}];
      var phrase = ethnosCadence.planSemanticPhrase(steps,{{durationMinMs:{seconds * 1000},durationMaxMs:{seconds * 1000}}});
      enterPlan(steps,{{score:phrase,channel:'test'}},[],'hawkes-plain-box')
        .then(result => completed=result);
    """)
    pump(clock)
    assert value(clock, "completed.ok") is True
    assert value(clock, "writes") == [
        [i, t] for i, t in enumerate(value(clock, "phrase.offsets"))
    ]
    assert [s[:2] for s in value(clock, "sounds")] == value(clock, "writes")
    # The route is reported by the writer that took it, not inferred by a
    # reader of the log.
    assert value(clock, "completed.transport") == "hawkes-plain-box"
    assert value(clock, "completed.timing.nativeWrites") == 4
    assert value(clock, "completed.timing.keypadWrites") == 0


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
    clock.eval(
        "writeSettings({...completed,entryGenre:'electronic'}).then(()=>readSettings()).then(s=>completed=s)"
    )
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
  var connections = 0, started = [];
  function audioNode() {
    const param={value:0,setTargetAtTime(){},setValueAtTime(){},
      linearRampToValueAtTime(){},exponentialRampToValueAtTime(){}};
    let connected=false;
    return {gain:param,frequency:param,threshold:param,knee:param,ratio:param,
      Q:param,detune:param,type:'sine',buffer:null,
      connect(){if(!connected){connections++;connected=true;}},
      disconnect(){if(connected){connections--;connected=false;}},
      start(at){started.push(at);},stop(){}};
  }
  var device = {state:'suspended',currentTime:0,destination:{},sampleRate:48000,
    baseLatency:0.01,outputLatency:0.02,
    createGain:audioNode,createDynamicsCompressor:audioNode,
    createBiquadFilter:audioNode,createOscillator:audioNode,
    createBufferSource:audioNode,
    createBuffer:(channels,frames)=>({getChannelData:()=>new Array(frames).fill(0)}),
    resume:()=>new Promise(()=>{}),
    suspend(){this.state='suspended';return Promise.resolve();},
    close(){this.state='closed';connections=0;return Promise.resolve();}};
  var note={character:'2',role:'number',offsetMs:0,beat:0,accent:false};
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


def test_cancel_releases_observer_and_context_and_old_completion_cannot_stop_new_run(
    clock,
):
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


STRUCTURED_FIXTURE = """
  var cues = [];
  var serial = 0;
  var boxIds = ['answer'];
  var boxes = {};
  var bases = {};
  class HTMLInputElement {
    constructor(id) {this.id=id; this.held='';}
    get value() {return this.held;} set value(v) {this.held=v;}
    focus() {document.activeElement=this; control.CurrentBase=bases[this.id];}
    getBoundingClientRect() {return {width:100};}
    dispatchEvent(e) {writes.push([this.id, now]);}
  }
  function addBox(id) {
    boxes[id] = new HTMLInputElement(id);
    bases[id] = {Type:'Base', loadExponent(){}, objMyDiv:{querySelector:()=>boxes[id]},
      qualifyLoadFraction:()=>true, qualifyLoadExponent:()=>true,
      setFocus(){control.CurrentBase=bases[id];}, arrChildObjects:[]};
    boxIds.push(id);
    return boxes[id];
  }
  var document = {
    activeElement: null,
    querySelectorAll: selector => selector.includes('customMessageBox') ? []
      : boxIds.map(id => boxes[id]),
    getElementById: id => boxes[id] ?? null,
    dispatchEvent: event => { cues.push([now, JSON.parse(event.detail)]); },
  };
  class InputEvent { constructor(type, options) {this.type=type; Object.assign(this,options);} }
  class CustomEvent { constructor(type, options) {this.type=type; Object.assign(this,options);} }
  var TEMPLATES = ['Exponent','Fraction','Radical','IndexedRadical','PBrace','Mod','Clear','BS'];
  // One entry point for both, as the editor has. `addElement` handles the
  // templates and special keys first and falls through to an ordinary
  // character, which it writes into the slot its `CurrentBase` owns -- so a
  // character that lands proves the editor's own cursor was where the plan
  // meant it to be. A template takes real time and does not add every box in
  // one tick, which is what `settle` exists to wait out.
  var control = {enabled:true, arrChildObjects:[], keyPadButtonClick(name) {
    if (!TEMPLATES.includes(name)) {
      const base = control.CurrentBase;
      const box = base && base.objMyDiv.querySelector('input.qbaseCSS');
      if (box) { box.held += name; writes.push([box.id, now]); }
      return;
    }
    setTimeout(() => { addBox('slot'+(serial+1)); }, 400);
    setTimeout(() => { addBox('slot'+(serial+2)); serial += 2; }, 700);
  }};
  var window = {quant_wp_UI:{controlsCollection:[control], focusedElementIndex:0}};
  boxes.answer = new HTMLInputElement('answer');
  bases.answer = {Type:'Base', loadExponent(){}, objMyDiv:{querySelector:()=>boxes.answer},
    qualifyLoadFraction:()=>true, qualifyLoadExponent:()=>true,
    setFocus(){control.CurrentBase=bases.answer;}, arrChildObjects:[]};
  control.arrChildObjects=[bases.answer];
  control.CurrentBase=bases.answer;
  var addBoxTracked = addBox;
  addBox = id => { const box = addBoxTracked(id); control.arrChildObjects.push(bases[id]); return box; };
"""


def test_editor_structure_holds_the_phrase_instead_of_bursting_the_rest_of_it(clock):
    """A template is a fermata: the notes after it keep the score's spacing."""
    load(clock, "page-actions.js")
    clock.eval(STRUCTURED_FIXTURE)
    clock.eval("""
      var steps = [{op:'type',text:'12'},{op:'template',name:'Exponent'},{op:'type',text:'345'}];
      var phrase = ethnosCadence.planSemanticPhrase(steps,{durationMinMs:2000,durationMaxMs:2000});
      enterPlan(steps,{score:phrase,channel:'test'},[],'hawkes-dynamic-keypad')
        .then(result => completed=result);
    """)
    pump(clock)
    assert value(clock, "completed.ok") is True
    offsets = value(clock, "phrase.offsets")
    struck = [at for _id, at in value(clock, "writes")]

    # The editor really did hold the phrase, and the writer says by how much.
    held = value(clock, "completed.timing.heldMs")
    assert held > 0
    assert value(clock, "completed.timing.maxLatenessMs") == 0

    # Every note after the hold keeps the interval the score gave it. Without
    # the fermata they all came due at once and arrived in the same tick.
    intervals = [round(b - a) for a, b in zip(struck, struck[1:])]
    planned = [round(b - a) for a, b in zip(offsets, offsets[1:])]
    assert intervals[2:] == planned[2:]
    assert min(intervals[2:]) > 0

    # The structure announced itself once, naming itself and its own hold.
    structural = [cue for _at, cue in value(clock, "cues") if len(cue) == 4]
    assert [cue[2] for cue in structural] == ["Exponent"]
    assert structural[0][0] == 2 and structural[0][3] == round(held)

    # Every character of it went through the editor's own keypad, including the
    # five digits that could have been assigned straight into the box.
    assert value(clock, "completed.transport") == "hawkes-dynamic-keypad"
    assert value(clock, "completed.timing.keypadWrites") == 5
    assert value(clock, "completed.timing.nativeWrites") == 0


def test_the_device_places_voices_on_the_score_not_on_the_wake_up_jitter(clock):
    """Jitter smaller than the lead is absorbed; a real stall re-anchors once."""
    clock.eval(FAKE_AUDIO)
    clock.eval("""
      var instrument = new CadenceInstrument(()=>device);
      instrument.unlock(); device.state='running';
      // Three notes 500 ms apart in the score, delivered with ±12 ms of jitter,
      // then a fourth whose write was stalled for a third of a second.
      var arrivals = [[0,0],[0.512,500],[0.988,1000],[1.840,1500]];
      var scheduled = [];
      for (const [clockTime, offsetMs] of arrivals) {
        device.currentTime = clockTime;
        const before = started.length;
        instrument.strike({character:'2',role:'number',offsetMs,beat:0},0,{genre:'classical'});
        scheduled.push(Math.round(started[before]*1000));   // the character's own voice
      }
      var holds = instrument.timing();
    """)
    scheduled = value(clock, "scheduled")
    gaps = [b - a for a, b in zip(scheduled, scheduled[1:])]
    # The first three notes are exactly 500 ms apart in the output, though the
    # writes that caused them were 512 and 476 ms apart.
    assert gaps[:2] == [500, 500]
    # The stalled write cannot be played in the past, so it re-anchors: one late
    # note, and the correction is not carried into the rest of the phrase.
    assert value(clock, "holds.reanchors") == 1
    # It starts as soon as it may -- the write's own time plus the minimum lead
    # -- rather than at the score time that has already gone by.
    assert scheduled[3] == 1840 + 8
    # No voice is ever held longer than the perceptual lock allows.
    assert max(value(clock, "holds.holds")) <= 60
    assert min(value(clock, "holds.holds")) >= 8


def test_a_held_phrase_re_enters_in_tempo_rather_than_measuring_from_the_hold(clock):
    clock.eval(FAKE_AUDIO)
    clock.eval("""
      var instrument = new CadenceInstrument(()=>device);
      instrument.unlock(); device.state='running';
      instrument.strike({character:'1',role:'number',offsetMs:0,beat:0},0,{genre:'lofi'});
      device.currentTime = 0.400;
      instrument.strikeStructure('Fraction',{genre:'lofi'});
      // The editor held the phrase for 400 ms; the score's own clock did not
      // move, so the note after it is still note 1 at its own offset.
      device.currentTime = 0.410;
      var beforeHold = started.length;
      instrument.strike({character:'2',role:'number',offsetMs:500,beat:1},1,{genre:'lofi'});
      var afterHold = Math.round(started[beforeHold]*1000);
      device.currentTime = 0.930;
      var beforeNext = started.length;
      instrument.strike({character:'3',role:'number',offsetMs:1000,beat:2},2,{genre:'lofi'});
      var next = Math.round(started[beforeNext]*1000);
    """)
    # The fermata drops the anchor, so the first note back sets a fresh one and
    # the one after it lands exactly its scored 500 ms later.
    assert value(clock, "afterHold") == 440
    assert value(clock, "next") == 940
    assert value(clock, "instrument.timing().reanchors") == 0


@pytest.mark.parametrize("genre", ["classical", "jazz", "lofi", "electronic"])
def test_each_arrangement_is_a_different_reading_of_one_unchanged_score(clock, genre):
    clock.eval(f"""
      var steps = [{{op:'template',name:'Fraction'}},{{op:'type',text:'2x+3'}},
        {{op:'slot',name:'denominator'}},{{op:'type',text:'5y'}}];
      var phrase = ethnosCadence.planSemanticPhrase(steps);
      var voiced = phrase.notes.map((note,i) => arrangeNote(note,i,{{genre:{json.dumps(genre)}}}));
      var reference = phrase.notes.map((note,i) => arrangeNote(note,i,{{genre:'classical'}}));
    """)
    voiced = value(clock, "voiced")
    assert [note["offsetMs"] for note in voiced] == value(clock, "phrase.offsets")
    # The character's own voice is always exactly on its score offset. Only the
    # accompaniment may carry the arrangement's feel, and never by much.
    for note in voiced:
        for layer in note["layers"]:
            if layer["kind"] == "melody":
                assert layer.get("delayMs", 0) == 0 and layer.get("feel") is not True
        assert 0 <= note["feelMs"] <= 30
    if genre != "classical":
        assert voiced != value(clock, "reference")


def test_arrangements_differ_in_harmony_percussion_and_timbre_not_only_waveform(clock):
    clock.eval("""
      var phrase = ethnosCadence.planSemanticPhrase([{op:'type',text:'2x+3y-7'}]);
      var byGenre = {};
      for (const genre of ['classical','jazz','lofi','electronic']) {
        const voiced = phrase.notes.map((note,i) => arrangeNote(note,i,{genre}));
        byGenre[genre] = {
          chords: voiced.flatMap(n => n.layers.filter(l => l.kind==='chord').map(l => l.midi)),
          drums: voiced.flatMap(n => n.layers.filter(l => l.kind==='percussion')
            .map(l => l.percussion)),
          types: [...new Set(voiced.flatMap(n => n.layers.map(l => l.type)))].sort(),
          attacks: [...new Set(voiced.flatMap(n => n.layers.map(l => l.attack)))].sort(),
          feel: voiced[0].feelMs,
        };
      }
    """)
    by_genre = value(clock, "byGenre")
    # Four different harmonisations of the same seven notes.
    assert len({tuple(g["chords"]) for g in by_genre.values()}) == 4
    # Percussion is a real difference, not a waveform swap.
    assert by_genre["classical"]["drums"] == []
    assert set(by_genre["jazz"]["drums"]) == {"ride", "rim"}
    assert set(by_genre["lofi"]["drums"]) == {"kick", "hat"}
    assert set(by_genre["electronic"]["drums"]) == {"sub", "hat"}
    # And so are register, envelope and feel.
    assert by_genre["lofi"]["chords"][0] < by_genre["jazz"]["chords"][0]
    assert len({tuple(g["attacks"]) for g in by_genre.values()}) == 4
    assert [
        by_genre[g]["feel"] for g in ["classical", "jazz", "lofi", "electronic"]
    ] == [0, 20, 26, 0]


def test_the_background_instrument_reopens_its_device_rather_than_resuming_it(clock):
    """A page with no user activation cannot rely on resuming what it suspended."""
    load(clock, "cadence-session.js")
    clock.eval(FAKE_AUDIO)
    clock.eval("""
      var opened = 0;
      insertionInstrument.contextFactory = () => {opened++; return {...device,state:'running'};};
      insertionInstrument.unlock();
      var first = insertionInstrument.context.state;
      insertionInstrument.finish();
      var betweenAnswers = insertionInstrument.context;
      insertionInstrument.unlock();
      var second = insertionInstrument.context.state;
    """)
    assert value(clock, "first") == "running"
    assert value(clock, "betweenAnswers") is None
    assert value(clock, "second") == "running"
    assert value(clock, "opened") == 2
    clock.eval("cancelCadence()")


def test_a_forged_structure_cue_cannot_advance_or_extend_the_phrase(clock):
    load(clock, "cadence-session.js")
    clock.eval("""
      var phrase=ethnosCadence.planSemanticPhrase([{op:'type',text:'12'}]);
      var session=createCadencePresentation({tabId:7,frameId:0},phrase,{enabled:false},
        cue=>views.push(cue.structure ?? cue.index),()=>true);
      var port={name:session.channel,sender:{tab:{id:7},frameId:0},
        onMessage:{addListener(fn){this.fn=fn;}},onDisconnect:{addListener(fn){this.fn=fn;}},
        postMessage(){},disconnect(){}};
      attachCadencePort(port);
      port.onMessage.fn({index:0,elapsedMs:0,structure:true,label:'Fraction',heldMs:200});
      port.onMessage.fn({index:0,elapsedMs:0,structure:true,label:'x'.repeat(64),heldMs:0});
      port.onMessage.fn({index:0,elapsedMs:0});
      port.onMessage.fn({index:1,elapsedMs:400});
      port.onMessage.fn({index:2,elapsedMs:800});
    """)
    # The structure is announced, the over-long label is dropped, and neither
    # can move the note counter or add a note the score does not contain.
    assert value(clock, "views") == ["Fraction", 0, 1]


def test_a_refused_insertion_reports_no_performance_of_its_own(clock):
    """A run clears the last measurement, so no run inherits an earlier one."""
    load(clock, "cadence-session.js")
    clock.eval("""
      var phrase = ethnosCadence.planSemanticPhrase([{op:'type',text:'12'}]);
      function run(deliver) {
        beginCadenceRun();
        const session = createCadencePresentation(
          {tabId:7,frameId:0}, phrase, {enabled:false}, ()=>{}, ()=>true);
        const port = {name:session.channel, sender:{tab:{id:7},frameId:0},
          onMessage:{addListener(fn){this.fn=fn;}},
          onDisconnect:{addListener(fn){this.fn=fn;}},
          postMessage(){}, disconnect(){}};
        attachCadencePort(port);
        deliver(port);
        session.close(false);
        return cadenceMeasurements();
      }
      var performed = run(port => {
        port.onMessage.fn({index:0,elapsedMs:0});
        port.onMessage.fn({index:1,elapsedMs:400});
      });
      var readAgain = cadenceMeasurements();
      var refused = run(() => {});
    """)
    assert value(clock, "performed.notes") == 2
    # Asking twice is fine; a run that accepted no character at all reports
    # nothing rather than the previous answer's numbers.
    assert value(clock, "readAgain") == value(clock, "performed")
    assert value(clock, "refused") is None
