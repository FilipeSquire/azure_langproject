# app.py
import os
import textwrap
import streamlit as st
from dotenv import load_dotenv, find_dotenv
from openai import APIConnectionError
import json
from profile_agent import profileAgent
# If you saved the helpers as rag_core.py, use: from rag_core import ...
# If you kept them in rag.py, change the import below accordingly.
from rag import (
    retrieve,            # (mode, hits) = retrieve(query, k)
    retrieve_hybrid,
    retrieve_semantic,
    retrieve_hybrid_enhanced,
    build_context,       # ctx = build_context(hits, text_field=TEXT_FIELD)
    get_aoai_client,     # AzureOpenAI client factory
    AOAI_DEPLOYMENT,     # deployment name (e.g., gpt-4o-mini / o3-mini / gpt-5)
    TEXT_FIELD,          # your text field (e.g., "chunk")
)

# Blob save is optional; if you don't have it in your module, comment this import out.
# from rag import save_markdown_to_blob  # requires AZURE_STORAGE_CONNECTION_STRING + AZURE_BLOB_CONTAINER

load_dotenv(find_dotenv(), override=True)

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


st.set_page_config(page_title="Oraculum v2", layout="wide")
st.title("📄 Oraculum v2 (Azure Version)")

if "history" not in st.session_state:
    st.session_state.history = []

output_placeholder = st.empty()
k = st.sidebar.slider("Top-K chunks", 40, 100, 200)
ts = st.sidebar.slider("Max Text Recall Size", 40, 200, 400)
cs = st.sidebar.slider("Max Chars in Context Given to AI ", 500, 15000, 30000)

save_toggle = st.sidebar.checkbox("Auto-save last answer to Blob", value=False)

client = get_aoai_client()

def maybe_route_to_action(prompt: str, client, deployment: str) -> bool:
    """
    Returns True if the tool was invoked and handled here (so skip RAG),
    otherwise False to continue with your normal RAG flow.
    """
    try:
        resp = client.chat.completions.create(
            model=deployment,
            tools=TOOLS,
            tool_choice="auto",  # let the model decide
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
            # <<< Your real workflow will run here later >>>

            agent1 = profileAgent(company)
            out_pdf = agent1._rag_answer()

            st.download_button(
                        "Download Profile PDF",
                        data=out_pdf,
                        file_name=f"{company}_profile.pdf",
                        mime="application/pdf",
                    )
            st.success("Profile creation done.")

            st.markdown(f"**Functionality in construction..**  (requested company: `{company}`)")
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
            # score    = h.get("score", 0.0)
            snippet  = (h.get(TEXT_FIELD) or "")
            snippet  = textwrap.shorten(snippet, width=800, placeholder=" ...")
            st.markdown(f"**[{i}]** *title:* `{title}` — *chunk_id:* `{chunk_id}` — *score:* {score:.4f}")
            st.write(snippet)

    # 3) Build context for the model
    sys = (
        "You are a helpful analyst. Use ONLY the provided context to answer. "
        "Cite sources using [#] that match the snippet numbers. "
        "If the answer isn't in the context, say you don't know."
    )
    ctx = build_context(hits, text_field=TEXT_FIELD, max_chars=cs)

    messages = [
        {"role": "system", "content": sys},
        {"role": "user",   "content": f"Question:\n{prompt}\n\nContext snippets (numbered):\n{ctx}"},
    ]

    # 4) Stream the model answer with a robust delta loop; fallback to non-streaming if needed
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

    st.session_state.history.append({"q": prompt, "a": full})

    # 5) Optional: save to Blob
    # if save_toggle:
    #     name = st.text_input("Filename to save (.md)", value="answer.md", key="fn")
    #     if st.button("Save to Blob Storage"):
    #         try:
    #             url = save_markdown_to_blob(full, name)
    #             st.success(f"Saved: {url}")
    #         except Exception as e:
    #             st.error(f"Failed to save to Blob: {e}")

# --- Chat UI ---
prompt = st.chat_input("Ask about the ingested PDFs…")
if prompt:
    with st.chat_message("user"):
        st.write(prompt)
    with st.chat_message("assistant"):
        # Try tool routing first
        if maybe_route_to_action(prompt, client, AOAI_DEPLOYMENT):
            pass  # handled by tool; skip RAG
        else:
            stream_answer(prompt, k)  # your existing RAG flow

