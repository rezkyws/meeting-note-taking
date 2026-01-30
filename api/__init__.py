"""
AI Meeting Note Taker - Secure API Module

Provides secure API endpoints for the browser extension.
"""

from .auth import validate_api_key, generate_api_key
from .models import TranscribeRequest, TranscribeResponse, NotesRequest, NotesResponse

__all__ = [
    "validate_api_key",
    "generate_api_key", 
    "TranscribeRequest",
    "TranscribeResponse",
    "NotesRequest",
    "NotesResponse",
]
