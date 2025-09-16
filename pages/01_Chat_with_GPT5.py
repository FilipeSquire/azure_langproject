# app.py
import os
import textwrap
import streamlit as st
from dotenv import load_dotenv, find_dotenv
from openai import APIConnectionError
import json
import streamlit as st

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

from profile_agent import profileAgent
from profile_agent_web import profileAgentWeb
from gpts.gpt5_web import WebAgent
from gpts.gpt_assistants import maybe_route_to_action
from azure.blob_functions import companyHouseListAdd
from azure.adf_functions import trigger_function
from azure.search_functions import run_indexer
from gpts.gpt_assistants import question_to_machine
from gpts.tools import TOOLS3
import time

load_dotenv(find_dotenv(), override=True)
# =====================================================
# GPT TOOLS 
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

client = get_aoai_client()

# ========================================
def check_actions(prompt, client, deployment, k, ts, cs, model_profile) -> bool:

    calls = maybe_route_to_action(prompt, client, deployment)

    if not calls:
        return False

    for call in calls:
        if call.function.name == "create_company_profile":
            args = json.loads(call.function.arguments or "{}")
            company = args.get("companyName") or "(unknown)"

            agent1 = WebAgent(
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
        elif call.function.name == 'add_company':
            args = json.loads(call.function.arguments or "{}")
            companyNumber = args.get("companyNumber") or "(unknown)"
            
            try:
                companyHouseListAdd(CompanyNumber = companyNumber)
                st.success(f"Added {companyNumber} to internal list...")
            except Exception as e:
                print(f'Adding to internal list problem \n{e}')

            try:
                trigger_function(companyNumber = companyNumber)
                st.success(f"Downloaded {companyNumber} files...")
            except Exception as e:
                print(f'Downloading file problem \n{e}')

            try:
                st.success("Running OCR and Vectorization, come back in 10 minutes ... ")
                run_indexer()
            except Exception as e:
                print(f'OCR and Vector problem \n{e}')
            
            return True


    return False

def stream_answer(prompt: str):
    agent = WebAgent()

    answer_text = agent._answer(prompt)

    st.session_state.history.append({"q": prompt, "a": answer_text})

    ph = st.empty()
    buf = ""
    for ch in answer_text:
        buf += ch
        ph.write(buf)
        time.sleep(0.008)


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
        if check_actions(
                prompt, client, AOAI_DEPLOYMENT,model_profile=model_profile):
            pass
        else:
            stream_answer(prompt)
