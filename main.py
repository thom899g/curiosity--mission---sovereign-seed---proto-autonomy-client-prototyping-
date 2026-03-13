"""
Sovereign Seed - Cognitive Membrane Core System
Main FastAPI application with modular architecture for Week 1 deployment.
"""

import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Any

from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from firebase_config import (
    initialize_firebase,
    verify_token,
    get_firestore_db,
    get_current_user,
    User
)
from models.document_models import DocumentUpload, DocumentResponse

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Initialize Firebase on startup
initialize_firebase()

# Create FastAPI application with metadata
app = FastAPI(
    title="Sovereign Seed Cognitive Membrane",
    description="Personal intelligence amplifier with Socratic interface",
    version="0.1.0-alpha",
    docs_url="/docs" if __debug__ else None,  # Disable in production
    redoc_url="/redoc" if __debug__ else None
)

# CORS configuration for development
origins = [
    "http://localhost:3000",
    "http://localhost:8080",
    "https://sovereign-seed.web.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global error handler for unexpected exceptions
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global error handler for all uncaught exceptions"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
            "error_id": f"ERR-{int(time.time())}",
            "timestamp": datetime.utcnow().isoformat()
        }
    )

# Health check endpoint (no auth required)
@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    return {
        "status": "healthy",
        "service": "cognitive_membrane",
        "version": "0.1.0-alpha",
        "timestamp": datetime.utcnow().isoformat(),
        "firebase_connected": True
    }

# Protected endpoints (require authentication)
@app.get("/api/v1/user/profile")
async def get_user_profile(current_user: User = Depends(get_current_user)):
    """Get current user's profile"""
    try:
        logger.info(f"Fetching profile for user: {current_user.uid}")
        db = get_firestore_db()
        
        user_doc = db.collection("users").document(current_user.uid).get()
        if not user_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User profile not found"
            )
            
        user_data = user_doc.to_dict()
        return {
            "uid": current_user.uid,
            "email": user_data.get("email"),
            "created_at": user_data.get("created_at"),
            "tier": user_data.get("tier", "free"),
            "documents_count": user_data.get("documents_count", 0)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching user profile: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch user profile"
        )

@app.post("/api/v1/documents/upload")
async def upload_document(
    upload_data: DocumentUpload,
    current_user: User = Depends(get_current_user)
):
    """Upload document metadata (actual file upload handled separately)"""
    logger.info(f"Document upload request from user: {current_user.uid}")
    
    # Check tier limits
    db = get_firestore_db()
    user_ref = db.collection("users").document(current_user.uid)
    user_doc = user_ref.get()
    
    if user_doc.exists:
        user_data = user_doc.to_dict()
        tier = user_data.get("tier", "free")
        doc_count = user_data.get("documents_count", 0)
        
        # Tier limits
        if tier == "free" and doc_count >= 3:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Free tier limit reached (3 documents). Upgrade to upload more."
            )
        elif tier == "basic" and doc_count >= 50:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Basic tier limit reached (50 documents). Upgrade for unlimited."
            )
    
    # Store document metadata
    try:
        document_data = {
            "user_id": current_user.uid,
            "filename": upload_data.filename,
            "file_type": upload_data.file_type,
            "size_bytes": upload_data.size_bytes,
            "status": "pending_upload",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        # Add to Firestore
        doc_ref = db.collection("documents").add(document_data)
        
        # Update user document count
        user_ref.update({
            "documents_count": doc_count + 1,
            "updated_at": datetime.utcnow().isoformat()
        })
        
        logger.info(f"Document metadata stored: {doc_ref[1].id}")
        
        return {
            "document_id": doc_ref[1].id,
            "upload_url": f"/api/v1/documents/{doc_ref[1].id}/upload-file",
            "status": "metadata_stored",
            "message": "Document metadata stored. Use upload-url to upload file."
        }
        
    except Exception as e:
        logger.error(f"Failed to store document metadata: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store document metadata"
        )

@app.get("/api/v1/documents")
async def list_documents(
    current_user: User = Depends(get_current_user),
    limit: int = 20,
    offset: int = 0
):
    """List user's documents with pagination"""
    try:
        db = get_firestore_db()
        
        # Query user's documents
        docs_ref = db.collection("documents").where("user_id", "==", current_user.uid)
        
        # Apply pagination
        documents = []
        for doc in docs_ref.limit(limit).offset(offset).stream():
            doc_data = doc.to_dict()
            doc_data["id"] = doc.id
            documents.append(doc_data)
        
        # Get total count
        total_count = len([doc for doc in docs_ref.stream()])
        
        return {
            "documents": documents,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": total_count,
                "has_more": (offset + limit) < total_count
            }
        }
        
    except Exception as e:
        logger.error(f"Error listing documents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list documents"
        )

# Week 1 placeholder endpoints (to be implemented)
@app.post("/api/v1/conversations/start")
async def start_conversation(
    current_user: User = Depends(get_current_user)
):
    """Start a new conversation with the Cognitive Membrane"""
    return {
        "conversation_id": f"conv_{int(time.time())}",
        "status": "active",
        "message": "Conversation started. Ask your first question about your documents.",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/api/v1/conversations/{conversation_id}/ask")
async def ask_question(
    conversation_id: str,
    question: str,
    current_user: User = Depends(get_current_user)
):
    """Ask a question about your documents"""
    logger.info(f"Question from {current_user.uid}: {question[:50]}...")
    
    # Placeholder response for Week 1
    return {
        "conversation_id": conversation_id,
        "question": question,
        "answer": "This is a placeholder response. Document analysis capabilities will be implemented in Week 1, Days 3-4.",
        "sources": [],
        "integrity_score": 0.0,
        "is_placeholder": True,
        "timestamp": datetime.utcnow().isoformat()
    }

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Sovereign Seed Cognitive Membrane...")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=__debug__,
        log_level="info"
    )