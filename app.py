import os
import tempfile
import streamlit as st
from dotenv import load_dotenv
from services.rag_engine import ResearchAssistant
from services.pdf_export import report_to_pdf

load_dotenv()
st.set_page_config(page_title="PaperPilot | RAG Research Assistant", page_icon="📘", layout="wide")

st.markdown("""
<style>
.block-container {max-width: 1180px; padding-top: 1.8rem;}
.hero {padding: 1.5rem 1.7rem; border-radius: 18px; color: white;
background: linear-gradient(120deg,#101c3a 0%,#174ea6 58%,#0891b2 100%); margin-bottom: 1.2rem;}
.hero h1 {color:white; font-size:2.25rem; margin:0;}
.hero p {color:#e0f2fe; margin:.45rem 0 0 0;}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="hero">
<h1>📘 PaperPilot</h1>
<p>Research-paper Q&A powered by retrieval-augmented generation and live web evidence.</p>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.header("Configuration")
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    tavily_key = os.getenv("TAVILY_API_KEY", "")
    st.write("Gemini", "✅ Ready" if gemini_key else "⚠️ API key missing")
    st.write("Tavily", "✅ Ready" if tavily_key else "⚠️ API key missing")
    st.caption("Set keys in a `.env` file and restart the app.")
    st.markdown("[Get a Gemini API key](https://aistudio.google.com/app/apikey)")
    st.markdown("[Get a Tavily API key](https://app.tavily.com/)")
    st.divider()
    use_web = st.toggle("Allow web search", value=True)
    st.caption("Web search is used when the question needs current or external information.")

left, right = st.columns([1.15, 1])
with left:
    st.subheader("1. Add a research paper")
    uploaded = st.file_uploader("Upload a PDF", type=["pdf"])
    if uploaded:
        st.success(f"Selected: {uploaded.name} ({uploaded.size / 1024:.1f} KB)")
        st.caption("The PDF is processed for this session; it is not uploaded to a public service by this app.")
with right:
    st.subheader("2. Ask a question")
    question = st.text_area(
        "Question",
        placeholder="Example: Explain the paper's main contribution and compare it with recent approaches.",
        height=125
    )
    depth = st.select_slider("Answer detail", options=["Brief", "Standard", "Detailed"], value="Standard")
    ask = st.button("✨ Research answer", type="primary", use_container_width=True)

if ask:
    if not question.strip():
        st.warning("Enter a question first.")
    elif not uploaded:
        st.warning("Upload a research-paper PDF first.")
    elif not gemini_key:
        st.error("GEMINI_API_KEY is missing. Add it to your .env file.")
    elif use_web and not tavily_key:
        st.error("TAVILY_API_KEY is missing. Add it to your .env file, or turn off web search.")
    else:
        assistant = ResearchAssistant(gemini_api_key=gemini_key, tavily_api_key=tavily_key if use_web else None)
        progress = st.status("Preparing your research…", expanded=True)
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(uploaded.getvalue())
                pdf_path = tmp.name
            try:
                progress.write("Reading and indexing the PDF…")
                assistant.index_pdf(pdf_path, uploaded.name)
                progress.write("Choosing the best evidence sources…")
                result = assistant.answer(question.strip(), allow_web=use_web, detail=depth)
            finally:
                try:
                    os.unlink(pdf_path)
                except OSError:
                    pass
            progress.update(label="Answer ready", state="complete", expanded=False)
            st.session_state["last_result"] = result
            st.session_state["last_question"] = question.strip()
            st.session_state["last_filename"] = uploaded.name
        except Exception as exc:
            progress.update(label="Research failed", state="error", expanded=True)
            st.error(str(exc))
            st.info("Check your API keys and terminal logs. If the error mentions a model name, set GEMINI_MODEL in .env to a model available to your API key.")

if "last_result" in st.session_state:
    result = st.session_state["last_result"]
    st.divider()
    st.subheader("Research answer")
    st.caption(f"Question: {st.session_state.get('last_question', '')} · Document: {st.session_state.get('last_filename', '')}")
    st.markdown(result["answer"])
    c1, c2, c3 = st.columns(3)
    c1.metric("PDF passages", len(result["document_evidence"]))
    c2.metric("Web sources", len(result["web_sources"]))
    c3.metric("Chosen route", result["route"].replace("_", " ").title())
    tab1, tab2, tab3 = st.tabs(["📚 Sources", "🧩 Retrieved PDF passages", "🧭 Research decision"])
    with tab1:
        if result["web_sources"]:
            for i, source in enumerate(result["web_sources"], 1):
                with st.expander(f"[W{i}] {source.get('title') or source.get('url')}"):
                    st.write(source.get("snippet", ""))
                    st.markdown(f"[Open source]({source['url']})")
        else:
            st.info("No web sources were needed for this question.")
        st.markdown("**PDF source**")
        st.write(st.session_state.get("last_filename", "Uploaded PDF"))
    with tab2:
        if not result["document_evidence"]:
            st.info("No relevant PDF passages were retrieved.")
        for i, item in enumerate(result["document_evidence"], 1):
            with st.expander(f"PDF passage {i} · page {item.get('page', '?')}"):
                st.write(item["text"])
    with tab3:
        st.write(result["reason"])
        st.caption("The routing decision is an LLM-assisted heuristic, not an independent verification step.")
    pdf_data = report_to_pdf(
        title="PaperPilot Research Answer",
        question=st.session_state.get("last_question", ""),
        answer=result["answer"],
        web_sources=result["web_sources"],
        document_name=st.session_state.get("last_filename", "")
    )
    st.download_button("⬇️ Download answer as PDF", data=pdf_data, file_name="paperpilot_answer.pdf", mime="application/pdf")
    st.download_button("⬇️ Download answer as Markdown", data=result["answer"].encode("utf-8"), file_name="paperpilot_answer.md", mime="text/markdown")

st.divider()
st.caption("PaperPilot is a student project prototype. Check original papers and source websites before relying on important claims.")
