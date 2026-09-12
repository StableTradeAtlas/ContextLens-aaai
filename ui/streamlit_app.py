from __future__ import annotations

try:
    import streamlit as st
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Streamlit is not installed. Run `pip install -r requirements.txt`.") from exc

from app.agent import answer_question
from app.ingest import ingest
from app.storage import count_records


if count_records() == 0:
    ingest(use_live=False, seed_if_empty=True)

st.set_page_config(page_title="ContextLens 文脉镜", layout="wide")
st.title("ContextLens 文脉镜")
st.caption("Traceable public historical-investigation agent for Shanghai Library open data.")

question = st.text_area(
    "输入一个人物、旧地址、事件、文献或城市记忆线索",
    "南京路的百货公司、报刊广告和市民生活可以串成怎样的城市记忆路线？",
    height=110,
)
mode = st.selectbox(
    "调查模式",
    ["trace_person", "explore_place", "reconstruct_event", "read_document", "city_memory", "family_memory", "shanghai_world"],
    index=4,
)
style = st.selectbox(
    "输出风格",
    ["investigation_dossier", "evidence_brief", "timeline", "brief", "policy_analogy"],
    index=0,
)
if st.button("Generate traceable historical dossier", type="primary"):
    result = answer_question(question, language="zh", mode=mode, output_style=style)
    st.subheader("一句话发现")
    st.write(result.get("one_line_finding", ""))
    st.subheader("原型诊断")
    st.json(result.get("award_readiness", {}))
    st.subheader("Problem Summary")
    st.write(result["problem_summary"])
    st.subheader("Evidence Cards")
    for c, line in zip(result["citations"], result["historical_evidence"]):
        with st.container(border=True):
            st.markdown(f"**{c['title']}**")
            st.write(line)
            st.caption(
                f"{c['dataset']} | {c.get('evidence_type', '')} | "
                f"{'live API' if c['live_api'] else 'demo seed'} | {c['uri']}"
            )
            if c.get("verification_notes"):
                st.caption("复核备注：" + "；".join(c["verification_notes"]))
    st.subheader("Mechanism Comparison")
    st.write(result["mechanism_comparison"])
    st.subheader("Claim Ledger")
    st.json((result.get("investigation") or {}).get("claims", []))
    st.subheader("Future Questions")
    for q in result["future_questions"]:
        st.markdown(f"- {q}")
    st.subheader("Audit")
    st.json(result["audit"])
