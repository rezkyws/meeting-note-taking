"""
API Request/Response Models

Pydantic models for input validation and response serialization.
All validation happens server-side for security.
"""

from typing import Optional
from pydantic import BaseModel, Field, field_validator
import base64


class TranscribeRequest(BaseModel):
    """Request to transcribe audio."""
    
    audio_data: str = Field(
        ...,
        description="Base64-encoded audio data",
        min_length=100,  # Reasonable minimum for audio
    )
    format: str = Field(
        default="webm",
        description="Audio format (webm, wav, mp3)",
    )
    language: Optional[str] = Field(
        default=None,
        description="Language code (e.g., 'en', 'id'). Auto-detect if None.",
    )
    
    @field_validator("audio_data")
    @classmethod
    def validate_audio_data(cls, v: str) -> str:
        """Validate that audio_data is valid base64."""
        try:
            decoded = base64.b64decode(v)
            if len(decoded) < 100:
                raise ValueError("Audio data too small")
            if len(decoded) > 10 * 1024 * 1024:  # 10MB max
                raise ValueError("Audio data too large (max 10MB)")
            return v
        except Exception as e:
            raise ValueError(f"Invalid base64 audio data: {e}")
    
    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        """Validate audio format."""
        allowed = ["webm", "wav", "mp3", "ogg", "flac"]
        if v.lower() not in allowed:
            raise ValueError(f"Invalid format. Allowed: {allowed}")
        return v.lower()


class TranscribeResponse(BaseModel):
    """Response from transcription."""
    
    success: bool
    segments: list[dict] = Field(default_factory=list)
    full_text: str = ""
    language_detected: Optional[str] = None
    duration_seconds: float = 0.0
    error: Optional[str] = None


class NotesRequest(BaseModel):
    """Request to generate meeting notes."""
    
    transcript: str = Field(
        ...,
        description="Meeting transcript text",
        min_length=10,
        max_length=100000,  # ~25k words max
    )
    context: Optional[str] = Field(
        default=None,
        description="Optional meeting context (topic, participants)",
        max_length=1000,
    )
    
    @field_validator("transcript")
    @classmethod
    def validate_transcript(cls, v: str) -> str:
        """Sanitize transcript text."""
        # Remove potential XSS/injection
        return v.strip()


class NotesUpdateRequest(BaseModel):
    """Request to update existing notes with new content."""
    
    new_transcript: str = Field(
        ...,
        description="New transcript segment to add",
        min_length=1,
        max_length=50000,
    )
    existing_notes: dict = Field(
        ...,
        description="Current notes to update",
    )
    
    @field_validator("existing_notes")
    @classmethod
    def validate_existing_notes(cls, v: dict) -> dict:
        """Validate notes structure."""
        required_keys = {"summary", "key_points", "action_items", "decisions", "questions"}
        if not all(key in v for key in required_keys):
            raise ValueError(f"Missing required keys in existing_notes: {required_keys}")
        return v


class NotesResponse(BaseModel):
    """Response with generated meeting notes."""
    
    success: bool
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    error: Optional[str] = None


class UsageResponse(BaseModel):
    """API usage statistics."""
    
    requests_count: int
    tier: str
    rate_limit: int
    rate_limit_remaining: int
    features: list[str]


class ErrorResponse(BaseModel):
    """Standard error response."""
    
    error: str
    code: str
    details: Optional[dict] = None
