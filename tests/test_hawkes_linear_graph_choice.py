"""Ordinary Hawkes options whose captions own complete linear graphs."""

from __future__ import annotations

import json
import re
from pathlib import Path

import quickjs

from ethnos.hawkes_host import handle
from facet_loopback import facet


GRAPH = Path(__file__).parents[1] / "extension" / "common" / "graph-actions.js"


PAGE = r"""
var now=0,timers=[];
var setTimeout=(fn,ms)=>{timers.push({fn,at:now+ms});return timers.length;};
var MouseEvent=class{constructor(type,init={}){this.type=type;Object.assign(this,init);}};
function visibleNode(){return {isConnected:true,getBoundingClientRect:()=>({width:200,height:160})};}
function element(name,text='',children=[]){return {localName:name,tagName:name,textContent:text,children,
  querySelector(selector){return selector==='graphobjects' ? this.children.find(one=>one.localName==='graphobjects')||null : null;}};}
var DOMParser=class{parseFromString(xml){
  const value=tag=>{const found=xml.match(new RegExp('<'+tag+'>([^<]*)</'+tag+'>'));return found?found[1]:'';};
  const points=[...xml.matchAll(/<point><x>([^<]+)<\/x><y>([^<]+)<\/y><\/point>/g)]
    .map(found=>element('point','',[element('x',found[1]),element('y',found[2])]));
  const line=element('line','',[element('type',value('type')),element('visible',value('visible')),
    element('definedby',value('definedby')),element('extend',value('extend')),...points]);
  const graph=element('graph','',[element('graphobjects','',[line])]);
  return {querySelector:()=>null,querySelectorAll:selector=>selector==='graph'?[graph]:[]};
}};
var selected=-1;
var mode={getUserAnswer:()=>selected<0?'':String(options[selected].data.Index),isEmpty:()=>selected<0};
var radios=[],labels=[],roots=[],options=[];
function setData(data,key,value){if(typeof data[key]==='function')data[key](value);else data[key]=value;}
function option(index,x1,y1,x2,y2){
  const root=visibleNode();roots.push(root);
  const label={...visibleNode(),id:'AqbOption'+index+'_lbl',contains:node=>node===root,
    querySelectorAll:selector=>selector==='svg[role="presentation"]'?[root]:[]};labels.push(label);
  const data={Index:index,Name:'AqbOption',ariaLabelledByValue:label.id,isOpt:true,
    enableState:true,visibleState:true,selectedState:false,activeMode:mode,
    caption:'<div><graph><graphobjects><line><type>line</type><visible>true</visible>'+ 
      '<definedby>twopoint</definedby><extend>both</extend>'+ 
      '<point><x>'+x1+'</x><y>'+y1+'</y></point><point><x>'+x2+'</x><y>'+y2+'</y></point>'+ 
      '</line></graphobjects></graph></div>'};
  const radio={...visibleNode(),type:'radio',disabled:false,checked:false,value:String(index),
    id:'UITemplateContainer_answerTemplateContainer_AqbOption'+index+'_opt',
    name:'UITemplateContainer_answerTemplateContainer_AqbOption',
    getAttribute:name=>name==='aria-labelledby'?label.id:'',dispatchEvent(event){if(event.type!=='click')return true;
      options.forEach(one=>{one.radio.checked=false;setData(one.data,'selectedState',false);});
      this.checked=true;setData(data,'selectedState',true);selected=options.indexOf(record);
      return true;
    }};radios.push(radio);
  const record={root,label,data,radio};options.push(record);return record;
}
// Deliberately neither semantic nor DOM order.
option(3,0,9,-9,0); option(1,0,-9,9,0); option(4,0,-9,-9,0); option(2,0,9,9,0);
var byId=Object.fromEntries([...radios,...labels].map(one=>[one.id,one]));
var document={
  getElementById:id=>byId[id]||null,querySelector:()=>null,
  querySelectorAll:selector=>selector==='svg[role="presentation"]'?[...roots].reverse()
    :selector==='input[type="radio"]'?radios
    :selector.includes('input.qbaseCSS')?[]
    :selector==='svg#svg_numberline'||selector==='#QGraph'||selector==='[id*="customMessageBox"]'?[]:[]
};
var window={location:{origin:'https://learn.hawkeslearning.com'},quant_wp_UI:{
  strUITemplateContainer:'UITemplateContainer_answerTemplateContainer',
  controlsCollection:options.map(one=>[one.radio]),controlsCollectionData:options.map(one=>one.data)}};
"""


def page() -> quickjs.Context:
    context = quickjs.Context()
    context.eval(PAGE)
    source = re.sub(r"^export ", "", GRAPH.read_text(encoding="utf-8"), flags=re.M)
    context.eval(source)
    return context


def run(context: quickjs.Context, offered=None):
    context.eval(
        "var done=null;Promise.resolve(graphOperation("
        + json.dumps(offered)
        + ")).then(value=>{done=value},error=>{done={ok:false,code:String(error)}});"
    )
    for _ in range(200):
        while context.execute_pending_job():
            pass
        if context.eval("done !== null"):
            break
        if not context.eval("timers.length"):
            break
        context.eval(
            "timers.sort((a,b)=>a.at-b.at);var timer=timers.shift();"
            "now=Math.max(now,timer.at);timer.fn();"
        )
    return json.loads(context.eval("JSON.stringify(done)"))


def test_option_caption_lines_are_described_from_exact_model_geometry() -> None:
    described = run(page())

    assert described["ok"] is True
    assert described["surface"] == "graph-choice"
    assert described["choices"] == [
        "Graph: line; slope=1; y-intercept=9",
        "Graph: line; slope=1; y-intercept=-9",
        "Graph: line; slope=-1; y-intercept=-9",
        "Graph: line; slope=-1; y-intercept=9",
    ]
    assert described["probe"] == {
        "engine": "caption-linear-graph-choice",
        "choices": 4,
        "ownership": "option-model-radio-aria-caption",
    }


def test_knockout_option_metadata_is_read_through_page_observables() -> None:
    context = page()
    context.eval(
        "window.ko={isObservable:value=>value?.observable===true};"
        "for(const one of options){for(const key of ['caption','enableState','visibleState','selectedState']){"
        "let held=one.data[key];const observable=function(next){if(arguments.length)held=next;return held};"
        "observable.observable=true;one.data[key]=observable;}}"
    )

    described = run(context)

    assert described["ok"] is True
    assert described["probe"]["engine"] == "caption-linear-graph-choice"


def test_semantic_choice_actuates_its_owned_radio_without_dom_order() -> None:
    context = page()
    described = run(context)

    result = run(
        context,
        {
            "choice": "Graph: line; slope=1; y-intercept=-9",
            "snapshot": described["snapshot"],
        },
    )

    assert result == {
        "ok": True,
        "code": "graph-choice-verified",
        "choice": "Graph: line; slope=1; y-intercept=-9",
        "selected": 1,
        "events": 1,
    }
    assert context.eval("selected") == 1
    assert context.eval("options[1].data.Index") == 1


def test_option_caption_ownership_mismatch_fails_closed() -> None:
    context = page()
    context.eval("options[0].radio.id='wrong-owner'")

    result = run(context)

    assert result["ok"] is False
    assert result["code"] == "graph-choice-option-ownership-unreadable"


def test_duplicate_line_meanings_fail_closed() -> None:
    context = page()
    context.eval("options[3].data.caption=options[0].data.caption")

    result = run(context)

    assert result["ok"] is False
    assert result["code"] == "graph-choice-option-contract-ambiguous"


def test_host_selects_the_semantic_line_with_zero_model_calls(monkeypatch) -> None:
    choices = [
        "Graph: line; slope=-1; y-intercept=9",
        "Graph: line; slope=1; y-intercept=9",
        "Graph: line; slope=-1; y-intercept=-9",
        "Graph: line; slope=1; y-intercept=-9",
    ]
    loopback = facet(monkeypatch)

    response = handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "linear-graph-choice",
            "origin": "https://learn.hawkeslearning.com",
            "solve_engine": "facet",
            "problem": {
                "prompt_text": "Choose the correct graph for the linear function.",
                "mathml": ["<math><mtext>f(x)=-(9-x)</mtext></math>"],
                "answer_shape": {"kind": "option", "count": 1, "choices": choices},
            },
        }
    )

    assert response.status == "ready", response
    assert response.answer.keyboard_entry == choices[3]
    assert response.certainty.method == "SymPy exact linear graph choice"
    assert response.certainty.model_calls == 0
    assert loopback.prompts == []
