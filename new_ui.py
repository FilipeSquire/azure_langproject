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

load_dotenv(find_dotenv(), override=True)

# =====================================================

st.set_page_config(page_title="Oraculum v2", layout="wide")
st.title("📄 Oraculum v2.1 (Azure Version)")

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
    st.write('How many notes are fetched; higher finds more, risks clutter.')
    ts = st.slider("Max Text Recall Size", 40, 200, 400)
    st.write('Maximum text pulled per note; larger gives context, may distract.')
    cs = st.slider("Max Chars in Context Given to AI ", 500, 15000, 30000)
    st.write('Hard limit the model reads; everything must fit underneath.')
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
    st.title("Define system script:")
    st.write('Sets behavior, tone, safety; high-level rules the model follows.')
    st.session_state.sys_message_mod = st.text_area(
        "System", value=st.session_state.sys_message_mod, key="sys_ta"
    )
    st.title("Define developer script:")
    st.write('App-specific instructions and tools; override user phrasing when conflicting.')
    st.session_state.dev_message_mod = st.text_area(
        "Developer", value=st.session_state.dev_message_mod, key="dev_ta"
    )
    st.title("Define Company Profile script:")
    st.session_state.profile_mod = st.text_area(
        "Profile", value= st.session_state.profile_mod , key="pro_ta"
    )
    st.title("Define Company Profile Web script:")
    st.session_state.profile_mod_web = st.text_area(
        "Profile Web", value= st.session_state.profile_mod_web , key="prow_ta"
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
