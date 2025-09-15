# app.py
import os
import textwrap
from dotenv import load_dotenv, find_dotenv
import json
from rag import (
    retrieve_hybrid_enhanced,
    build_context
)
from typing import List, Dict, Optional
from rag import retrieve_hybrid_enhanced, build_context
from gpts.gpt_assistants import question_to_machine
from openai import OpenAI, APIConnectionError
import streamlit as st

load_dotenv(find_dotenv(), override=True)

# ---- Config (same Azure Search envs you already use) ----
SEARCH_ENDPOINT = os.environ["AZURE_SEARCH_ENDPOINT"]
SEARCH_INDEX    = os.environ["AZURE_SEARCH_INDEX"]
SEARCH_KEY      = os.getenv("AZURE_SEARCH_API_KEY")  # omit if using AAD/RBAC
VECTOR_FIELD    = os.getenv("VECTOR_FIELD")
TEXT_FIELD      = os.getenv("TEXT_FIELD")

# ---- OpenAI (standard) config ----
OPENAI_API_KEY  = os.getenv("FELIPE_OPENAI_API_KEY")        # required
OPENAI_MODEL    = os.getenv("FELIPE_OPENAI_MODEL", "gpt-5")  # e.g., "gpt-5" or "gpt-5-mini"


class WebAgent():

    """
        - This class is responsible to operate calls and allow the usage of websearch
        - The websearch is activated through chat by mentioning "web search" in the paragraph
    """

    def __init__(self,
                k: int = 50,
                max_text_recall_size: int = 200,
                # max_chars: int,
                model: Optional[str] = OPENAI_MODEL,
                top = 20,
                max_output_tokens: int = 1200,
                reasoning_effort: str = "medium",      # "minimal" | "low" | "medium" | "high"
                verbosity: str = "medium",                 # "low" | "medium" | "high"
                tool_choice: str = "none",              # "none" | "auto" | {"type":"tool","name":"..."}
                streaming: bool = False
                ):

        # Parameters settings
        # self.company_name = company_name
        self.k = k
        self.max_text_recall_size = max_text_recall_size
        # self.max_chars = max_chars
        # ===================================
        # RAG PARAMETERS
        self.top = top
        self.k = k
        self.max_text_recall_size

        # ===================================
        # LLM settings
        self.model = model
        # self.temperature = temperature
        # self.top_p = top_p
        self.max_output_tokens = max_output_tokens
        self.reasoning_effort = reasoning_effort
        self.verbosity = verbosity
        self.streaming = streaming

        # OpenAI standard client
        self.web_openai = OpenAI(api_key=OPENAI_API_KEY)

    def _answer(self, question, stream = False):

        # 1. Identify TOOLS call

        # 2. Optimize call
        opt_user_query = question_to_machine(question, OPENAI_API_KEY)

        new_user_query = opt_user_query.output_text

        # 3. Call RAG
        mode, hits = retrieve_hybrid_enhanced(query=new_user_query, top = self.top, k = self.k, max_text_recall_size = self.max_text_recall_size)
        ctx = build_context(hits)
        # 4. Call model

        user_msg = f"Question:\n{new_user_query}\n\nContext snippets (numbered):\n{ctx}"
        system_msg = """"

        You are a restructuring analyst focused on identifying companies in financial distress that could be advisory targets for your company. 
        You prepare comprehensive, accurate and full analysis of companies highlighting liquidity issues, debt maturity risks and covenant pressure. 
        You rely on annual reports and financial statements of companies.

        WHEN the information is NOT FOUND in the context, you USE WEB SEARCH

        **Formatting and Editorial Standards**: 
            - Always **cite sources** 
            - Generate complete profile directly in the chat, take your time and don't compress important things 
            - Always write dates in the format "Mmm-yy" (e.g. Jun-24), fiscal years as "FYXX" (e.g. FY24, LTM1H25), and currencies in millions in the format "£1.2m" 
            - Always double-check revenue split 

        """
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user",   "content": user_msg},
        ]

        if stream:
            answer_box = st.empty()
            full = ""
            try:
                with self.web_openai.responses.stream(
                    model=self.model,
                    input=messages,
                    tools=[{"type": "web_search"}],
                    tool_choice="auto",
                    # max_output_tokens=self.max_output_tokens,
                    reasoning={"effort": self.reasoning_effort},
                    text={"verbosity": self.verbosity},
                ) as stream:
                    for event in stream:
                        if event.type == "response.output_text.delta":
                            piece = event.delta
                            if piece:
                                full += piece
                                answer_box.markdown(full)
                        elif event.type == "response.error":
                            raise RuntimeError(str(event.error))
                    final = stream.get_final_response()
                    if not full:
                        # fallback to final assembled text if no deltas arrived
                        full = getattr(final, "output_text", "") or ""
                        answer_box.markdown(full)
            except APIConnectionError:
                resp = self.web_openai.responses.create(
                    model=self.model,
                    input=messages,
                    tools=[{"type": "web_search"}],
                    tool_choice="auto",
                    # max_output_tokens=self.max_output_tokens,
                    reasoning={"effort": self.reasoning_effort},
                    text={"verbosity": self.verbosity},
                )
                full = getattr(resp, "output_text", "") or ""
                answer_box.markdown(full)

            return full

        
        resp = self.web_openai.responses.create(
                model=self.model,
                input=messages,
                tools=[{"type": "web_search"}],
                tool_choice="auto",
                # max_output_tokens=self.max_output_tokens,
                reasoning={"effort": self.reasoning_effort},
                text={"verbosity": self.verbosity},
            )
        answer_text = resp.output_text

        return answer_text