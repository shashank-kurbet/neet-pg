import streamlit as st
import json, random, datetime, os, zipfile, re, uuid, html
import pandas as pd
import altair as alt

DATA_PATH = "/mnt/data/train_fixed.json"
FALLBACK_NAME = "train.json"
HISTORY_FILE = "history.json"
DATA_SOURCE_USED = None

# ---------- robust loaders (same as before) ----------
def _try_json_load(text): return json.loads(text)
def _try_json_lines(text):
    objs = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln: continue
        objs.append(json.loads(ln))
    if not objs: raise ValueError("No JSON-lines")
    return objs
def _brace_scanner(text):
    objs = []; depth=0; start=None
    for i,ch in enumerate(text):
        if ch=='{':
            if depth==0: start=i
            depth+=1
        elif ch=='}':
            depth-=1
            if depth==0 and start is not None:
                objs.append(text[start:i+1]); start=None
    return [json.loads(o) for o in objs]
def _heuristic_commas(text):
    fixed = re.sub(r'}\s*{','},\n{', text); fixed = "[\n"+fixed.strip()+"\n]"; return json.loads(fixed)

def parse_text_to_list(text):
    try:
        c = _try_json_load(text)
        if isinstance(c, dict): return [c]
        if isinstance(c, list): return c
    except Exception: pass
    for fn in (_try_json_lines, _brace_scanner, _heuristic_commas):
        try:
            return fn(text)
        except Exception:
            pass
    raise ValueError("All parse strategies failed")

def load_text_from_possible_locations(local_name=FALLBACK_NAME):
    global DATA_PATH
    # prefer fixed
    if os.path.exists(DATA_PATH):
        return DATA_PATH, open(DATA_PATH,"r",encoding="utf-8",errors="ignore").read()
    # same dir
    cwd = os.getcwd()
    p = os.path.join(cwd, local_name)
    if os.path.exists(p):
        return p, open(p,"r",encoding="utf-8",errors="ignore").read()
    alt = os.path.join("/mnt/data", local_name)
    if os.path.exists(alt):
        return alt, open(alt,"r",encoding="utf-8",errors="ignore").read()
    # inside archive.zip
    for z in (os.path.join(cwd,"archive.zip"), "/mnt/data/archive.zip"):
        if os.path.exists(z):
            with zipfile.ZipFile(z,"r") as zf:
                if local_name in zf.namelist():
                    raw = zf.read(local_name).decode("utf-8",errors="ignore")
                    return f"{z}:{local_name}", raw
    raise FileNotFoundError(f"Could not find {local_name} or {DATA_PATH}")

def load_questions_from_file():
    global DATA_SOURCE_USED
    path_used, raw = load_text_from_possible_locations()
    DATA_SOURCE_USED = path_used
    parsed = parse_text_to_list(raw)
    valid=[]
    for i,item in enumerate(parsed, start=1):
        if not isinstance(item, dict): continue
        q = {
            "id": item.get("id", str(i)),
            "question": item.get("question",""),
            "opa": item.get("opa",""),
            "opb": item.get("opb",""),
            "opc": item.get("opc",""),
            "opd": item.get("opd",""),
            "cop": item.get("cop", None),
            "exp": item.get("exp","")
        }
        # normalize cop
        if isinstance(q["cop"], str):
            s=q["cop"].strip().lower(); m={"opa":1,"opb":2,"opc":3,"opd":4,"a":1,"b":2,"c":3,"d":4,"1":1,"2":2,"3":3,"4":4}
            q["cop"]=m.get(s, None)
            if q["cop"] is None:
                try: q["cop"]=int(s)
                except Exception: q["cop"]=None
        elif isinstance(q["cop"], (int,float)):
            try: q["cop"]=int(q["cop"])
            except: q["cop"]=None
        valid.append(q)
    if not valid: raise RuntimeError("No valid questions")
    return valid

# load
try:
    questions = load_questions_from_file()
except Exception as e:
    st.error(f"Error loading questions: {e}")
    st.stop()

# history helpers
def load_history():
    if not os.path.exists(HISTORY_FILE): return []
    try:
        with open(HISTORY_FILE,"r",encoding="utf-8") as f: return json.load(f)
    except Exception:
        return []
def save_history(h):
    with open(HISTORY_FILE,"w",encoding="utf-8") as f: json.dump(h,f,ensure_ascii=False,indent=2)

history = load_history()

# helper to render colored options (used both places)
def render_options_with_highlight_full(opa,opb,opc,opd, selected, correct):
    opts = [("A", opa), ("B", opb), ("C", opc), ("D", opd)]
    html_blocks=[]
    for label,text in opts:
        if not text or str(text).strip()=="":
            continue
        esc = html.escape(str(text))
        is_correct = (correct is not None and str(text)==str(correct))
        is_selected = (selected is not None and str(text)==str(selected))
        style = "padding:10px;border-radius:6px;margin:6px 0;display:block;"
        if is_correct:
            style += "background-color:#e6ffed;border:1px solid #2ecc71;color:#083d15;"
            prefix = "✔️"
        elif is_selected and not is_correct:
            style += "background-color:#ffecec;border:1px solid #e74c3c;color:#5b0b0b;"
            prefix = "✖️"
        else:
            style += "background-color:#f8f9fa;border:1px solid #ddd;color:#111;"
            prefix = ""
        html_blocks.append(f"<div style='{style}'><strong>{label}.</strong> {esc} <span style='float:right'>{prefix}</span></div>")
    if html_blocks:
        st.markdown("".join(html_blocks), unsafe_allow_html=True)

# session init
if "quiz" not in st.session_state or not st.session_state.get("quiz"):
    n = min(10, len(questions))
    st.session_state.quiz = random.sample(questions, n)
    st.session_state.submitted = False
    st.session_state.breakdown = []
    # NEW: Initialize score state
    st.session_state.last_score = 0
    st.session_state.last_total = 0
    for q in st.session_state.quiz:
        opts = [q.get("opa",""), q.get("opb",""), q.get("opc",""), q.get("opd","")]
        opts = [o for o in opts if o and str(o).strip()!=""]
        st.session_state[f"ans_{q['id']}"] = opts[0] if opts else None

# UI
st.sidebar.title("NEET PG Quiz App")
page = st.sidebar.radio("Navigation", ["Quiz","History","Progress"])

if page=="Quiz":
    st.title("🩺 NEET PG Quiz – 10 Random Questions")
    quiz = st.session_state.quiz

    with st.form("quiz_form"):
        for i,q in enumerate(quiz):
            st.subheader(f"Q{i+1}. {q.get('question','')}")
            options = [q.get("opa",""), q.get("opb",""), q.get("opc",""), q.get("opd","")]
            options = [o for o in options if o and str(o).strip()!=""]
            key = f"ans_{q['id']}"
            default = st.session_state.get(key) or (options[0] if options else None)
            idx = options.index(default) if default in options else 0
            st.radio("Select an answer:", options, key=key, index=idx)

            if st.session_state.submitted:
                sel = st.session_state.get(key)
                cop = q.get("cop")
                correct = None
                if isinstance(cop, int) and 1<=cop<=4:
                    correct = q.get(["opa","opb","opc","opd"][cop-1])
                else:
                    m=re.search(r"ans[\.\s:]*\(?([a-d1-4])\)?", (q.get("exp") or "").lower())
                    if m:
                        mapidx={"a":1,"b":2,"c":3,"d":4,"1":1,"2":2,"3":3,"4":4}
                        idxm=mapidx.get(m.group(1))
                        if idxm: correct = q.get(["opa","opb","opc","opd"][idxm-1])
                render_options_with_highlight_full(q.get("opa",""), q.get("opb",""), q.get("opc",""), q.get("opd",""), sel, correct)
                # explanation with HTML details (not Streamlit expander) to avoid nested expanders
                if q.get("exp"):
                    exp_html = f"<details><summary><strong>Explanation</strong></summary><div style='margin-top:8px'>{html.escape(q.get('exp'))}</div></details>"
                    st.markdown(exp_html, unsafe_allow_html=True)
            st.write("---")

        submitted_now = st.form_submit_button("Submit Quiz")

    if submitted_now:
        answers={}
        for q in quiz:
            answers[q['id']] = st.session_state.get(f"ans_{q['id']}")
        breakdown=[]
        score=0
        for q in quiz:
            cop=q.get("cop")
            correct=None
            if isinstance(cop,int) and 1<=cop<=4:
                correct = q.get(["opa","opb","opc","opd"][cop-1])
            else:
                m=re.search(r"ans[\.\s:]*\(?([a-d1-4])\)?", (q.get("exp") or "").lower())
                if m:
                    mi = {"a":1,"b":2,"c":3,"d":4,"1":1,"2":2,"3":3,"4":4}.get(m.group(1))
                    if mi: correct = q.get(["opa","opb","opc","opd"][mi-1])
            sel = answers.get(q['id'])
            is_correct = (sel==correct) if (sel is not None and correct is not None) else False
            if is_correct: score+=1
            # IMPORTANT: save full option texts so history can render consistently
            breakdown.append({
                "id": q['id'],
                "question": q.get("question",""),
                "opa": q.get("opa",""),
                "opb": q.get("opb",""),
                "opc": q.get("opc",""),
                "opd": q.get("opd",""),
                "selected": sel,
                "correct": correct,
                "is_correct": is_correct,
                "explanation": q.get("exp","")
            })
        attempt_id = str(uuid.uuid4())
        attempt_obj = {
            "attempt_id": attempt_id,
            "date": str(datetime.date.today()),
            "score": score,
            "total": len(quiz),
            "data_file": DATA_SOURCE_USED,
            "breakdown": breakdown
        }
        history.append(attempt_obj)
        save_history(history)
        st.session_state.submitted = True
        st.session_state.breakdown = breakdown
        # NEW: Store score/total in session state before the rerun
        st.session_state.last_score = score
        st.session_state.last_total = len(quiz)
        
        # force rerun so inline results appear immediately
        st.rerun() # <-- FIXED LINE
        
    # NEW BLOCK: Display the score only if the quiz has been submitted
    if st.session_state.submitted:
        # Use the stored score/total if available, defaulting to 0/10 if somehow missing
        display_score = st.session_state.get('last_score', 0)
        display_total = st.session_state.get('last_total', 10)
        
        # The lines the user wanted to execute:
        st.success(f"Your Score: {display_score}/{display_total} 🎉")
        st.balloons()
        
    # new quiz button
    st.markdown("---")
    c1,c2,c3 = st.columns([1,2,1])
    with c2:
        if st.button("🔁 New Quiz"):
            n=min(10,len(questions))
            st.session_state.quiz = random.sample(questions,n)
            st.session_state.submitted=False
            st.session_state.breakdown=[]
            # NEW: Reset score state when starting a new quiz
            st.session_state.last_score = 0
            st.session_state.last_total = 0
            for q in st.session_state.quiz:
                opts=[q.get("opa",""),q.get("opb",""),q.get("opc",""),q.get("opd","")]
                opts=[o for o in opts if o and str(o).strip()!=""]
                st.session_state[f"ans_{q['id']}"] = opts[0] if opts else None
            st.rerun() # <-- FIXED LINE

# HISTORY
elif page=="History":
    st.title("📜 Past Attempts (click to expand)")
    if not history:
        st.info("No history yet.")
    else:
        # newest first
        for attempt in sorted(history, key=lambda x: x.get("date",""), reverse=True):
            header = f"{attempt.get('date','?')} — Score {attempt.get('score','?')}/{attempt.get('total','?')}"
            src = attempt.get("data_file")
            if src: header += f" — dataset: {src}"
            with st.expander(header):
                st.write(f"Attempt ID: {attempt.get('attempt_id')}")
                st.write(f"Score: {attempt.get('score')}/{attempt.get('total')}")
                # breakdown: for each question render colored options and HTML details for explanation
                for idx,q in enumerate(attempt.get("breakdown",[]), start=1):
                    st.write(f"**Q{idx}. {q.get('question','')}**")
                    render_options_with_highlight_full(q.get("opa",""), q.get("opb",""), q.get("opc",""), q.get("opd",""), q.get("selected"), q.get("correct"))
                    if q.get("explanation"):
                        exp_html = f"<details><summary><strong>Explanation</strong></summary><div style='margin-top:8px'>{html.escape(q.get('explanation'))}</div></details>"
                        st.markdown(exp_html, unsafe_allow_html=True)
                    st.write("---")

# PROGRESS
elif page=="Progress":
    st.title("📈 Performance Over Time")
    if not history:
        st.info("No progress yet.")
    else:
        df = pd.DataFrame(history)
        if "date" in df.columns:
            try:
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date")
                if "total" in df.columns and "score" in df.columns:
                    df["percent"] = (df["score"]/df["total"]) * 100
                elif "score" in df.columns:
                    df["percent"] = df["score"]
                grouped = df.groupby(df["date"].dt.date).agg({"percent":"mean"}).reset_index().sort_values("date")
                chart = alt.Chart(grouped).mark_line(point=True).encode(x=alt.X("date:T",title="Date"), y=alt.Y("percent:Q",title="Score (%)")).properties(width=700,height=300)
                st.altair_chart(chart, use_container_width=True)
                st.write(grouped.set_index("date"))
            except Exception as e:
                st.error(f"Could not build chart: {e}")
                st.line_chart(df["score"])
        else:
            st.line_chart(pd.DataFrame(history)["score"])