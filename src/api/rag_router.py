"""
src/api/rag_router.py — RAG Learning Assistant endpoint.

Uses Groq for LLM responses grounded in uploaded document chunks.
Falls back gracefully when Groq is unavailable.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.db.models import DocumentChunk, Document, DocumentStatus
from src.api.auth_router import get_current_user
from src.ai.groq_client import generate_rag_answer, GroqServiceError, GroqNotConfiguredError
from src.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

# Number of chunks to retrieve for context
TOP_K_CHUNKS = 5


class RAGQueryRequest(BaseModel):
    question: str
    document_ids: Optional[list[str]] = None   # None = search all approved docs
    top_k: int = TOP_K_CHUNKS


class RAGSourceOut(BaseModel):
    document_name: str
    page_number: Optional[int]
    chunk_id: str


class RAGAnswerOut(BaseModel):
    answer: str
    sources: list[RAGSourceOut]
    grounded: bool
    groq_available: bool


@router.post("/ask", response_model=RAGAnswerOut)
def ask_assistant(
    body: RAGQueryRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Ask a question against the knowledge base.

    Retrieves relevant document chunks by keyword search,
    then generates a grounded answer using Groq.

    Note: Full semantic retrieval with ChromaDB is available
    when documents are indexed via the document upload pipeline.
    This endpoint falls back to SQLite text search when the
    vector store is not populated.
    """
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    # Retrieve relevant chunks — keyword-based fallback
    # (Semantic search via ChromaDB is wired through the document ingestion pipeline)
    question_terms = body.question.lower().split()[:10]

    chunks_query = (
        db.query(DocumentChunk)
        .join(Document, Document.id == DocumentChunk.document_id)
        .filter(Document.status == DocumentStatus.INDEXED)
        .filter(Document.is_approved == True)
    )

    if body.document_ids:
        chunks_query = chunks_query.filter(
            DocumentChunk.document_id.in_(body.document_ids)
        )

    # Simple keyword scoring: count how many terms appear in each chunk
    all_chunks = chunks_query.all()

    def _score_chunk(chunk: DocumentChunk) -> int:
        text_lower = (chunk.text or "").lower()
        return sum(1 for term in question_terms if term in text_lower)

    scored = sorted(all_chunks, key=_score_chunk, reverse=True)
    top_chunks = scored[: body.top_k]

    if not top_chunks:
        return RAGAnswerOut(
            answer=(
                "No relevant documents found in the knowledge base. "
                "Please upload and approve relevant learning materials first."
            ),
            sources=[],
            grounded=False,
            groq_available=settings.groq_available,
        )

    # Build context dicts
    context = [
        {
            "text": c.text,
            "document_name": c.document.original_filename if c.document else "Unknown",
            "page_number": c.page_number,
            "chunk_id": c.id,
        }
        for c in top_chunks
        if c.text
    ]

    # Generate answer with Groq
    if not settings.groq_available:
        # Return retrieved context without LLM generation
        excerpts = "\n\n---\n\n".join(
            f"[{ctx['document_name']}, p.{ctx.get('page_number', '?')}]:\n{ctx['text'][:500]}"
            for ctx in context
        )
        return RAGAnswerOut(
            answer=(
                "Groq AI is not configured. Here are the most relevant passages found:\n\n"
                + excerpts
            ),
            sources=[
                RAGSourceOut(
                    document_name=ctx["document_name"],
                    page_number=ctx.get("page_number"),
                    chunk_id=ctx["chunk_id"],
                )
                for ctx in context
            ],
            grounded=False,
            groq_available=False,
        )

    try:
        result = generate_rag_answer(
            question=body.question,
            context_chunks=context,
        )
        return RAGAnswerOut(
            answer=result["answer"],
            sources=[
                RAGSourceOut(
                    document_name=s.get("document_name", ""),
                    page_number=s.get("page_number"),
                    chunk_id=s.get("chunk_id", ""),
                )
                for s in result["sources"]
            ],
            grounded=result["grounded"],
            groq_available=True,
        )
    except GroqNotConfiguredError:
        raise HTTPException(
            status_code=503,
            detail="Groq is not configured. Set GROQ_API_KEY to enable AI answers.",
        )
    except GroqServiceError as exc:
        logger.warning("RAG Groq error: %s", str(exc)[:200])
        raise HTTPException(
            status_code=502,
            detail="AI assistant is temporarily unavailable. Please try again later.",
        )
