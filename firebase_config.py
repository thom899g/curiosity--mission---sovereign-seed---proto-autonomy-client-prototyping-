"""
Firebase configuration and authentication utilities for Sovereign Seed.
Handles initialization, authentication, and Firestore connections.
"""

import logging
import os
from typing import Optional, Dict, Any
from datetime import datetime

import firebase_admin
from firebase_admin import credentials, auth, firestore
from firebase_admin.exceptions import FirebaseError
from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

# Configure logging
logger = logging.getLogger(__name__)

# Firebase initialization flag
_firebase_initialized = False
_firestore_client = None

# Security scheme for Bearer tokens
security = HTTPBearer()

# User model
class User(BaseModel):
    """Authenticated user model"""
    uid: str
    email: Optional[str] = None
    tier: str = "free"

def initialize_firebase():
    """Initialize Firebase Admin SDK with error handling"""
    global _firebase_initialized, _firestore_client
    
    try:
        # Check if already initialized
        if _firebase_initialized:
            logger.info("Firebase already initialized")
            return
            
        # Get service account key path
        key_path = os.getenv("FIREBASE_KEY_PATH", "firebase-key.json")
        
        if not os.path.exists(key_path):
            logger.error(f"Firebase service account key not found at: {key_path}")
            raise FileNotFoundError(
                f"Firebase service account key not found. "
                f"Please place it at {key_path} or set FIREBASE_KEY_PATH env var."
            )
        
        # Initialize with error handling for duplicate apps
        try:
            cred = credentials.Certificate(key_path)
            firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin SDK initialized successfully")
        except ValueError as e:
            if "already exists" in str(e):
                logger.info("Firebase app already exists, using existing instance")
            else:
                raise
        
        # Initialize Firestore client
        _firestore_client = firestore.client()
        
        # Test connection
        test_connection()
        
        _firebase_initialized = True
        logger.info("Firebase configuration complete")
        
    except FileNotFoundError as e:
        logger.error(f"Firebase configuration failed: {e}")
        raise
    except Exception as e:
        logger.error(f"Firebase initialization error: {e}")
        raise RuntimeError(f"Failed to initialize Firebase: {e}")

def test_connection():
    """Test Firestore connection by creating a test document"""
    try:
        db = get_firestore_db()
        test_ref = db.collection("_system_tests").document("connection_test")
        test_ref.set({
            "timestamp": datetime.utcnow().isoformat(),
            "status": "success"
        })
        test_ref.delete()  # Clean up
        logger.debug("Firestore connection test passed")
    except Exception as e:
        logger.error(f"Firestore connection test failed: {e}")
        raise

def get_firestore_db():
    """Get Firestore database client with lazy initialization"""
    global _firestore_client
    
    if not _firebase_initialized:
        initialize_firebase()
    
    if _firestore_client is None:
        raise RuntimeError("Firestore client not initialized")
    
    return _firestore_client

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    """
    Verify Firebase ID token and return decoded token.
    Handles various error cases including expired tokens and invalid signatures.
    """
    if credentials is None:
        logger.warning("No credentials provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authentication token provided",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    
    try:
        # Verify the token with Firebase
        decoded_token = auth.verify_id_token(token)
        
        # Check if token is expired (Firebase should handle this, but we double-check)
        if decoded_token.get('exp', 0) < datetime.utcnow().timestamp():
            logger.warning("Token expired")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        logger.debug(f"Token verified for UID: {decoded_token.get('uid')}")
        return decoded_token
        
    except auth.ExpiredIdTokenError:
        logger.warning("Expired token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except auth.RevokedIdTokenError:
        logger.warning("Revoked token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except auth.InvalidIdTokenError:
        logger.warning("Invalid token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authent