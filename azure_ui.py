# app.py
import os
import textwrap
import streamlit as st
from dotenv import load_dotenv, find_dotenv
from openai import APIConnectionError
import json
from profile_agent import profileAgent
from profile_agent_web import profileAgentWeb
from rag import (
    retrieve,
    retrieve_hybrid,
    retrieve_semantic,
    retrieve_hybrid_enhanced,
    build_context,
    get_aoai_client,
    AOAI_DEPLOYMENT,
    TEXT_FIELD,
)
from theme_mod import apply_theme
from prompts import new_system_finance_prompt, finance_prompt_web
# from rag import save_markdown_to_blob  # optional
# =====================================================
# Theme


load_dotenv(find_dotenv(), override=True)
# =====================================================
# GPT TOOLS 
TOOLS = [{
    "type": "function",
    "function": {
        "name": "create_company_profile",
        "description": "Call when the user says something similar to: 'Create a company profile (CompanyName)'. Extract the name inside parentheses.",
        "parameters": {
            "type": "object",
            "properties": {"companyName": {"type": "string"}},
            "required": ["companyName"],
            "additionalProperties": False,
        },
    },
}]
# =====================================================

st.set_page_config(page_title="Oraculum v2", layout="wide")
st.title("📄 Oraculum v2 (Azure Version)")

# -------- Session state --------
if "history" not in st.session_state:
    st.session_state.history = []
if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt = None  # used by sidebar suggestion buttons
if "theme" not in st.session_state:
    st.session_state.theme = "dark"   # default: Dark Mode
if "sys_message_mod" not in st.session_state:
    st.session_state.sys_message_mod = """
        You are a financial analyst. Use ONLY the provided context to answer.
        All the files that you will be working with and PROVIDED in the context are annual reports. The name of the company that own the annual report is in the first page.
        Cite sources using [#] that match the snippet numbers.
        If the answer isn't in the context, say you don't know.
        """
if "dev_message_mod" not in st.session_state:
    st.session_state.dev_message_mod = "Ask about the ingested PDFs…"
if "profile_mod" not in st.session_state:
    st.session_state.profile_mod = new_system_finance_prompt
if "profile_mod_web" not in st.session_state:
    st.session_state.profile_mod_web = finance_prompt_web

output_placeholder = st.empty()
apply_theme(st.session_state.theme)

# =====================================================

# -------- Left sidebar with collapsible sections --------
with st.sidebar:
    mode = st.session_state.theme
    toggle_label = "White Mode" if mode == "dark" else "Dark Mode"
    if st.button(toggle_label, use_container_width=True, key="theme_toggle"):
        st.session_state.theme = "light" if mode == "dark" else "dark"
        st.rerun()
    st.markdown("---")

with st.sidebar.expander("GPT settings", expanded=True):
    k = st.slider("Top-K chunks", 40, 100, 200)
    ts = st.slider("Max Text Recall Size", 40, 200, 400)
    cs = st.slider("Max Chars in Context Given to AI ", 500, 15000, 30000)
    web_mode = st.checkbox("Activate web search for Profile Creation", value=False)
    # save_toggle = st.checkbox("Auto-save last answer to Blob", value=False)
    # model_mod = st.checkbox("Use o3 in chat. Defined standard is GPT5.", value=False)
    # model_profile_mod = st.checkbox("Use GPT5 to create Company Profile. Defined standard is o3", value=False)

with st.sidebar.expander("Recommended Questions", expanded=False):
    st.write('This section display a few ideas of questions to interact with the chatbot')
    st.write('Intructions: ')
    st.write('1. Select the first question to list company names')
    st.write("2. Inform the chatbot that you will be working with that company, like: 'Lets use the company company_name'")
    suggestions = [
        "Give me a list of company names available with annual report.",
        "Find any mentions of ESG strategy in the reports.",
        "Can you tell me the revenue for latest annual report",
        "What is the revenue growth of the company in the last two years",
        "What risks does the company highlight the most in the latest report?",
    ]
    for i, s in enumerate(suggestions):
        if st.button(s, key=f"sb_sugg_{i}", use_container_width=True):
            st.session_state.pending_prompt = s
            st.rerun()

with st.sidebar.expander("Script Mod", expanded=False):
    st.write("Define system script:")
    st.session_state.sys_message_mod = st.text_area(
        "System", value=st.session_state.sys_message_mod, key="sys_ta"
    )
    st.write("Define developer script:")
    st.session_state.dev_message_mod = st.text_area(
        "Developer", value=st.session_state.dev_message_mod, key="dev_ta"
    )
    st.write("Define Company Profile script:")
    st.session_state.profile_mod = st.text_area(
        "Profile", value= st.session_state.profile_mod , key="pro_ta"
    )
    st.write("Define Company Profile Web script:")
    st.session_state.profile_mod_web = st.text_area(
        "ProfileW", value= st.session_state.profile_mod_web , key="prow_ta"
    )

   


with st.sidebar.expander("Actions", expanded=False):
    st.write('List of possible actions by chat:')
    st.write('1. Create company profile.')
    st.write("To activate it you have to write: 'Create company profile of company_name with latest report'")

    st.write('Features in development:')
    st.write('1. Web Search')
    st.write('2. Feed new file through chat to system')
    st.write('3. Generate Company Profile PowerPoint')

client = get_aoai_client()

# ========================================
def maybe_route_to_action(prompt, client, deployment, k, ts, cs, model_profile) -> bool:
    """
    Returns True if the tool was invoked and handled here (so skip RAG),
    otherwise False to continue with your normal RAG flow.
    """
    try:
        resp = client.chat.completions.create(
            model=deployment,
            tools=TOOLS,
            tool_choice="auto",
            messages=[
                {"role": "system",
                 "content": "You are a router. If the user asks to 'Create company profile (Name)', call the function with the extracted name. Otherwise, do nothing."},
                {"role": "user", "content": prompt},
            ],
        )
    except APIConnectionError:
        return False

    msg = resp.choices[0].message
    calls = getattr(msg, "tool_calls", None)
    if not calls:
        return False

    for call in calls:
        if call.function.name == "create_company_profile":
            args = json.loads(call.function.arguments or "{}")
            company = args.get("companyName") or "(unknown)"

            if web_mode:
                agent1 = profileAgentWeb(
                    company,
                    k=k, max_text_recall_size=ts, max_chars=cs,
                    model=model_profile, profile_prompt=st.session_state.profile_mod_web
                )
            else:
                agent1 = profileAgent(
                    company,
                    k=k, max_text_recall_size=ts, max_chars=cs,
                    model=model_profile, profile_prompt=st.session_state.profile_mod
                )
                
            out_pdf = agent1._rag_answer()

            st.download_button(
                "Download Profile PDF",
                data=out_pdf,
                file_name=f"{company}_profile.pdf",
                mime="application/pdf",
            )
            st.success("Profile creation done.")
            st.markdown(f"**Functionality in construction..**  (requested company: `{company}`)")

            # Also persist this turn in the chat history so it shows up on rerun
            st.session_state.history.append({
                "q": prompt,
                "a": f"Created a company profile for **{company}**. Use the button above to download the PDF."
            })
            return True

    return False


def stream_answer(prompt: str, chunks: int):
    # 1) Retrieve
    mode, hits = retrieve_hybrid_enhanced(prompt, k=chunks, max_text_recall_size=ts)

    # 2) Show sources
    with st.expander(f"Retrieved snippets / sources — mode: {mode}"):
        for i, h in enumerate(hits, 1):
            title    = h.get("title")
            chunk_id = h.get("chunk_id")
            raw_score = h.get("score")
            try:
                score = float(raw_score) if raw_score is not None else 0.0
            except (TypeError, ValueError):
                score = 0.0
            snippet  = (h.get(TEXT_FIELD) or "")
            snippet  = textwrap.shorten(snippet, width=800, placeholder=" ...")
            st.markdown(f"**[{i}]** *title:* `{title}` — *chunk_id:* `{chunk_id}` — *score:* {score:.4f}")
            st.write(snippet)

    # 3) Build context for the model
    # sys = ( 
    #     "You are a financial analyst. Use ONLY the provided context to answer. "
    #     "All the files that you will be working with and PROVIDED in the context are annual reports. The name of the company that own the annual report is in the first page."
    #     "Cite sources using [#] that match the snippet numbers. "
    #     "If the answer isn't in the context, say you don't know."
    # )
    sys = st.session_state.sys_message_mod
    ctx = build_context(hits, text_field=TEXT_FIELD, max_chars=cs)

    messages = [
        {"role": "system", "content": sys},
        {"role": "user",   "content": f"Question:\n{prompt}\n\nContext snippets (numbered):\n{ctx}"},
    ]

    # 4) Stream the model answer
    st.markdown("### Answer")
    answer_box = st.empty()
    full = ""

    try:
        stream = client.chat.completions.create(
            model=AOAI_DEPLOYMENT,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
        )
        for chunk in stream:
            choices = getattr(chunk, "choices", None)
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            if not delta:
                continue
            piece = getattr(delta, "content", None)
            if piece:
                full += piece
                answer_box.markdown(full)
    except APIConnectionError:
        resp = client.chat.completions.create(
            model=AOAI_DEPLOYMENT,
            messages=messages,
        )
        full = resp.choices[0].message.content
        answer_box.markdown(full)

    # 5) Persist in chat history
    st.session_state.history.append({"q": prompt, "a": full})

    # 6) Optional blob save (left commented)
    # if save_toggle:
    #     name = st.text_input("Filename to save (.md)", value="answer.md", key="fn")
    #     if st.button("Save to Blob Storage"):
    #         try:
    #             url = save_markdown_to_blob(full, name)
    #             st.success(f"Saved: {url}")
    #         except Exception as e:
    #             st.error(f"Failed to save to Blob: {e}")

# --- Chat UI (persistent history; no clearing) ---

# Render prior turns every run so the conversation persists
for turn in st.session_state.history:
    with st.chat_message("user"):
        st.write(turn["q"])
    with st.chat_message("assistant"):
        st.write(turn["a"])

# Accept either a typed prompt or an injected one from sidebar suggestions
typed = st.chat_input("Ask about the ingested PDFs…")
pending = st.session_state.pop("pending_prompt", None)
prompt = typed or pending

if prompt:
    with st.chat_message("user"):
        st.write(prompt)
    with st.chat_message("assistant"):
        # Try tool routing first
        model_profile = "gpt-5" #if model_profile_mod else "o3"
        if maybe_route_to_action(
                prompt, client, AOAI_DEPLOYMENT,
                k=k, ts=ts, cs=cs, model_profile=model_profile):
            pass
        else:
            stream_answer(prompt, k)
