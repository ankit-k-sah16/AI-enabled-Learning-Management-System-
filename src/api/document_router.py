"""
src/api/document_router.py — Document upload and management endpoints.

Pipeline: Upload → Validate → Extract text → Chunk → Store in DB.
ChromaDB indexing is triggered asynchronously after storage.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.db.models import Document, DocumentChunk, DocumentStatus
from src.api.auth_router import get_current_user, require_admin
from src.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

# Upload storage path
UPLOAD_DIR = Path("data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Chunk configuration
CHUNK_SIZE = 800      # characters per chunk
CHUNK_OVERLAP = 100   # overlap between chunks


# ── Text extraction helpers ───────────────────────────────────────────────────

def _extract_pdf(content: bytes) -> list[tuple[int, str]]:
    """Extract (page_number, text) from PDF bytes."""
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(content))
        pages = []
        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append((i, text))
        return pages
    except ImportError:
        # Fallback: return raw bytes as single chunk
        logger.warning("pypdf not installed — PDF text extraction unavailable.")
        return [(1, content.decode("utf-8", errors="replace"))]
    except Exception as exc:
        logger.error("PDF extraction error: %s", str(exc))
        return []


def _extract_docx(content: bytes) -> list[tuple[int, str]]:
    """Extract text from DOCX bytes."""
    try:
        from docx import Document as DocxDocument
        doc = DocxDocument(io.BytesIO(content))
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        return [(1, text)]
    except Exception as exc:
        logger.error("DOCX extraction error: %s", str(exc))
        return []


def _extract_pptx(content: bytes) -> list[tuple[int, str]]:
    """Extract text from PPTX bytes."""
    try:
        from pptx import Presentation
        prs = Presentation(io.BytesIO(content))
        slides = []
        for i, slide in enumerate(prs.slides, start=1):
            texts = []
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    texts.append(shape.text)
            slides.append((i, "\n".join(texts)))
        return slides
    except Exception as exc:
        logger.error("PPTX extraction error: %s", str(exc))
        return []


def _chunk_text(
    pages: list[tuple[int, str]],
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[dict]:
    """
    Split page texts into overlapping chunks.

    Returns list of {chunk_index, text, page_number, token_count}.
    """
    chunks = []
    idx = 0
    for page_num, text in pages:
        text = text.strip()
        if not text:
            continue
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append({
                    "chunk_index": idx,
                    "text": chunk_text,
                    "page_number": page_num,
                    "token_count": len(chunk_text.split()),
                })
                idx += 1
            start = end - overlap
            if start >= len(text):
                break
    return chunks


# ── Endpoints ─────────────────────────────────────────────────────────────────

class DocumentOut(BaseModel):
    id: str
    original_filename: str
    file_type: str
    file_size_bytes: int
    status: str
    is_approved: bool
    total_chunks: int
    uploaded_at: str
    error_message: Optional[str]


@router.post("/upload", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Upload a learning document (PDF, DOCX, PPTX).
    Validates, extracts text, chunks, and stores in DB.
    """
    # Validate extension
    ext = Path(file.filename or "").suffix.lstrip(".").lower()
    if ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not allowed. Allowed: {settings.allowed_extensions}",
        )

    content = await file.read()

    # Size check
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum size of {settings.max_upload_size_mb} MB.",
        )

    # Generate unique storage filename
    file_id = str(uuid.uuid4())
    stored_filename = f"{file_id}.{ext}"
    file_path = UPLOAD_DIR / stored_filename

    # Save to disk
    with open(file_path, "wb") as f:
        f.write(content)

    # Create DB record
    doc = Document(
        uploader_id=current_user.id,
        filename=stored_filename,
        original_filename=file.filename or stored_filename,
        file_type=ext,
        file_size_bytes=len(content),
        status=DocumentStatus.PROCESSING,
        is_approved=False,
    )
    db.add(doc)
    db.flush()

    # Extract and chunk text
    try:
        if ext == "pdf":
            pages = _extract_pdf(content)
        elif ext == "docx":
            pages = _extract_docx(content)
        elif ext == "pptx":
            pages = _extract_pptx(content)
        else:
            pages = []

        if not pages or not any(text.strip() for _, text in pages):
            doc.status = DocumentStatus.FAILED
            doc.error_message = "No extractable text found in document."
            db.commit()
            raise HTTPException(
                status_code=422,
                detail="Could not extract text from the uploaded document.",
            )

        chunks = _chunk_text(pages)
        for chunk in chunks:
            db_chunk = DocumentChunk(
                document_id=doc.id,
                chunk_index=chunk["chunk_index"],
                text=chunk["text"],
                page_number=chunk["page_number"],
                token_count=chunk["token_count"],
            )
            db.add(db_chunk)

        doc.total_chunks = len(chunks)
        doc.status = DocumentStatus.INDEXED
        doc.processed_at = datetime.now(timezone.utc)
        db.commit()

        return {
            "document_id": doc.id,
            "filename": doc.original_filename,
            "total_chunks": doc.total_chunks,
            "status": doc.status.value,
            "message": "Document uploaded and indexed. Pending admin approval.",
        }

    except HTTPException:
        raise
    except Exception as exc:
        doc.status = DocumentStatus.FAILED
        doc.error_message = str(exc)[:500]
        db.commit()
        logger.error("Document processing failed for %s: %s", doc.id, str(exc))
        raise HTTPException(status_code=500, detail="Document processing failed.")


@router.get("/list", response_model=list[DocumentOut])
def list_documents(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List documents. Learners see approved+indexed docs; admins see all."""
    q = db.query(Document)
    if current_user.role.value == "learner":
        q = q.filter(
            Document.is_approved == True,
            Document.status == DocumentStatus.INDEXED,
        )
    docs = q.order_by(Document.uploaded_at.desc()).all()
    return [
        DocumentOut(
            id=d.id,
            original_filename=d.original_filename,
            file_type=d.file_type,
            file_size_bytes=d.file_size_bytes,
            status=d.status.value,
            is_approved=d.is_approved,
            total_chunks=d.total_chunks,
            uploaded_at=d.uploaded_at.isoformat(),
            error_message=d.error_message,
        )
        for d in docs
    ]


@router.post("/{document_id}/approve")
def approve_document(
    document_id: str,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Approve a document for use in RAG queries (admin only)."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    doc.is_approved = True
    db.commit()
    return {"document_id": doc.id, "is_approved": True}


@router.delete("/{document_id}")
def delete_document(
    document_id: str,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Delete a document and its chunks (admin only)."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Remove file from disk
    file_path = UPLOAD_DIR / doc.filename
    if file_path.exists():
        file_path.unlink()

    db.delete(doc)
    db.commit()
    return {"message": f"Document '{doc.original_filename}' deleted."}
