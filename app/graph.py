"""
LangGraph 2-Node RAG Pipeline for DarGlobal + Wasalt Real Estate Chatbot
Clean 2-Node State Machine:
START -> retrieve -> generate -> END
With thread-based session memory via MemorySaver.
"""

import logging
from typing import Annotated, Dict, Any, List, Optional
from typing_extensions import TypedDict

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    SystemMessage
)
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

from app.config import settings
from app.prompts import (
    SYSTEM_PROMPT_GROUNDED,
    is_arabic
)
from app.retriever import RealEstateRetriever
from app.llm import ResilientLLM

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State Definition
# ---------------------------------------------------------------------------
class AgentState(TypedDict):
    """LangGraph conversation and RAG state."""
    messages: Annotated[List[BaseMessage], add_messages]
    query: str
    route: str  # "greeting" | "off_topic" | "real_estate"
    filters: Dict[str, Any]
    retrieved_docs: List[Dict[str, Any]]
    context_text: str
    answer: str
    sources: List[Dict[str, str]]


# ---------------------------------------------------------------------------
# Filter Extraction Helper
# ---------------------------------------------------------------------------
def extract_search_filters(query: str) -> Dict[str, Any]:
    """
    Extract property attributes and filters from query text.
    Handles bilingual English and Arabic keywords.
    """
    filters = {}
    q = query.lower()

    # City / Location recognition
    if any(k in q for k in ["riyadh", "الرياض"]):
        filters["city"] = "Riyadh"
    elif any(k in q for k in ["jeddah", "جدة"]):
        filters["city"] = "Jeddah"
    elif any(k in q for k in ["dubai", "دبي"]):
        filters["city"] = "Dubai"
    elif any(k in q for k in ["muscat", "oman", "مسقط", "عمان"]):
        filters["city"] = "Muscat"
    elif any(k in q for k in ["london", "لندن"]):
        filters["city"] = "London"
    elif any(k in q for k in ["makkah", "مكة"]):
        filters["city"] = "Makkah"
    elif any(k in q for k in ["khobar", "الخبر", "dammam", "الدمام"]):
        filters["city"] = "Khobar"
    elif any(k in q for k in ["qatar", "doha", "قطر", "الدوحة"]):
        filters["city"] = "Doha"

    # Property type recognition
    if any(k in q for k in ["apartment", "flat", "شقة", "شقق"]):
        filters["property_type"] = "apartment"
    elif any(k in q for k in ["villa", "فيلا", "فلل"]):
        filters["property_type"] = "villa"
    elif any(k in q for k in ["penthouse", "بنتهاوس"]):
        filters["property_type"] = "penthouse"
    elif any(k in q for k in ["townhouse", "تاون هاوس"]):
        filters["property_type"] = "townhouse"
    elif any(k in q for k in ["land", "أرض", "اراضي"]):
        filters["property_type"] = "land"

    # Source platform recognition
    if any(k in q for k in ["darglobal", "dar global", "دار جلوبال", "aston martin", "pagani", "trump"]):
        filters["source"] = "darglobal"
    elif any(k in q for k in ["wasalt", "وصلت", "saudi property", "rent in riyadh", "rent in jeddah"]):
        filters["source"] = "wasalt"

    # Listing type (rent / sale)
    if any(k in q for k in ["rent", "إيجار", "للايجار", "للإيجار"]):
        filters["listing_type"] = "rent"
    elif any(k in q for k in ["buy", "sale", "بيع", "للبيع"]):
        filters["listing_type"] = "sale"

    return filters


# ---------------------------------------------------------------------------
# 2 Graph Nodes: retrieve & generate
# ---------------------------------------------------------------------------
class ChatbotNodes:
    """Implementation of the 2 pipeline nodes: retrieve and generate."""

    def __init__(self):
        self.retriever = RealEstateRetriever()
        self.llm = ResilientLLM()

    def retrieve_node(self, state: AgentState) -> Dict[str, Any]:
        """
        Node 1: retrieve
        Extracts metadata filters (city, property type, source) from the query,
        queries the ChromaDB vector store via retriever, formats the context text,
        and extracts source citations.
        """
        query = state.get("query", "")
        if not query and state.get("messages"):
            for m in reversed(state["messages"]):
                if isinstance(m, HumanMessage) or getattr(m, "type", "") == "human":
                    query = m.content
                    break

        # 1. Extract metadata filters
        filters = extract_search_filters(query)
        logger.info(f"Extracted filters for '{query[:40]}...': {filters}")

        # 2. Query ChromaDB vector store
        docs = self.retriever.retrieve(query=query, filters=filters)
        context = self.retriever.format_context(docs)

        # Citations removed per DRG-16 directive
        sources = []

        logger.info(f"Retrieved {len(docs)} documents for query: '{query[:40]}...'")
        return {
            "query": query,
            "route": "real_estate",
            "filters": filters,
            "retrieved_docs": docs,
            "context_text": context,
            "sources": []
        }

    def generate_node(self, state: AgentState) -> Dict[str, Any]:
        """
        Node 2: generate
        Combines system prompt, verified context, and conversation history,
        invokes ResilientLLM, and outputs the final answer and updated message history.
        """
        query = state.get("query", "")
        context = state.get("context_text", "")
        docs = state.get("retrieved_docs", [])
        messages = state.get("messages", [])
        route = state.get("route", "real_estate")

        # Grounded system instruction
        system_instruction = (
            f"{SYSTEM_PROMPT_GROUNDED}\n\n"
            f"=== VERIFIED REAL ESTATE CONTEXT FROM DARGLOBAL & WASALT ===\n"
            f"{context if context else 'No matching property listings found in database.'}\n"
            f"=== END CONTEXT ==="
        )

        llm_messages = [SystemMessage(content=system_instruction)]

        # Include recent history (last 6 messages) for multi-turn conversational context
        recent_history = [m for m in messages if isinstance(m, (HumanMessage, AIMessage))][-6:]
        llm_messages.extend(recent_history)

        # Invoke LLM (passes docs to enable grounded fallback if offline)
        answer = self.llm.invoke(
            messages=llm_messages,
            context_docs=docs if route == "real_estate" else None
        )

        return {
            "answer": answer,
            "messages": [AIMessage(content=answer)]
        }


# ---------------------------------------------------------------------------
# 2-Node Graph Construction
# ---------------------------------------------------------------------------
def create_rag_graph():
    """
    Build and compile the 2-node LangGraph StateGraph:
    START -> retrieve -> generate -> END
    With thread-based session memory via MemorySaver.
    """
    nodes = ChatbotNodes()
    workflow = StateGraph(AgentState)

    # Exactly 2 Nodes
    workflow.add_node("retrieve", nodes.retrieve_node)
    workflow.add_node("generate", nodes.generate_node)

    # Clean linear pipeline: START -> retrieve -> generate -> END
    workflow.add_edge(START, "retrieve")
    workflow.add_edge("retrieve", "generate")
    workflow.add_edge("generate", END)

    # Thread checkpoint memory
    checkpointer = MemorySaver()
    app = workflow.compile(checkpointer=checkpointer)
    return app


# Singleton graph instance
rag_app = create_rag_graph()


def run_chat(
    query: str,
    thread_id: str = "default_session"
) -> Dict[str, Any]:
    """
    High-level entry point for executing a chat turn.
    Returns:
        {
            "answer": str,
            "sources": List[Dict[str, str]],
            "route": str,
            "thread_id": str,
            "retrieved_count": int
        }
    """
    config = {"configurable": {"thread_id": thread_id}}
    initial_input = {
        "messages": [HumanMessage(content=query)],
        "query": query
    }

    final_state = rag_app.invoke(initial_input, config=config)

    return {
        "answer": final_state.get("answer", ""),
        "sources": final_state.get("sources", []),
        "route": final_state.get("route", "real_estate"),
        "thread_id": thread_id,
        "retrieved_count": len(final_state.get("retrieved_docs", []))
    }
