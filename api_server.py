"""
AI Meeting Note Taker - Secure API Server

Main API server for the browser extension. All sensitive logic
(transcription, LLM calls, rate limiting) runs server-side.

Usage:
    python api_server.py
"""

import asyncio
import base64
import io
import json
import logging
import os
import tempfile
import time
import concurrent.futures
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from api.middleware import RateLimitMiddleware, RequestLoggingMiddleware, require_feature
from api.models import (
    TranscribeRequest, TranscribeResponse,
    NotesRequest, NotesUpdateRequest, NotesResponse,
    UsageResponse, ErrorResponse
)
from api.auth import validate_api_key, generate_api_key

from src.transcription.engine import WhisperTranscriber
from src.llm.note_taker import NoteTaker, MeetingNotes


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Thread pool for blocking operations
executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="api")


class APIState:
    """Global API state."""
    def __init__(self):
        self.transcriber: Optional[WhisperTranscriber] = None
        self.note_taker: Optional[NoteTaker] = None
        self.active_streams: dict[str, WebSocket] = {}


state = APIState()


def get_transcriber() -> WhisperTranscriber:
    """Get or create transcriber instance."""
    if state.transcriber is None:
        state.transcriber = WhisperTranscriber(model_size="base")
    return state.transcriber


def get_note_taker() -> NoteTaker:
    """Get or create note taker instance."""
    if state.note_taker is None:
        state.note_taker = NoteTaker()
    return state.note_taker


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("AI Noter API Server starting...")
    # Pre-load models in background
    logger.info("Pre-loading transcription model...")
    get_transcriber().load_model()
    logger.info("API Server ready!")
    yield
    # Cleanup
    logger.info("Shutting down API server...")
    executor.shutdown(wait=True)


# Create FastAPI app
app = FastAPI(
    title="AI Meeting Note Taker API",
    description="Secure API for browser extension",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS for browser extension
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "chrome-extension://*",  # Chrome extensions
        "moz-extension://*",     # Firefox extensions
        "http://localhost:*",    # Local development
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add security middleware
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RateLimitMiddleware, default_limit=60, window_seconds=60)


# ==================== Health & Auth Endpoints ====================

@app.get("/health")
async def health_check():
    """Health check endpoint (no auth required)."""
    return {"status": "healthy", "timestamp": time.time()}


@app.post("/api/v1/auth/validate")
async def validate_api_key_endpoint(request: Request):
    """Validate an API key and return its details."""
    key_data = getattr(request.state, "api_key_data", None)
    if not key_data:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    return {
        "valid": True,
        "tier": key_data.tier,
        "features": key_data.features,
        "rate_limit": key_data.rate_limit,
    }


@app.get("/api/v1/usage")
async def get_usage(request: Request):
    """Get API usage statistics."""
    key_data = request.state.api_key_data
    
    return UsageResponse(
        requests_count=key_data.requests_count,
        tier=key_data.tier,
        rate_limit=key_data.rate_limit,
        rate_limit_remaining=key_data.rate_limit,  # Will be updated by middleware
        features=key_data.features,
    )


# ==================== Transcription Endpoints ====================

@app.post("/api/v1/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(
    data: TranscribeRequest,
    request: Request,
    _=Depends(require_feature("transcribe"))
):
    """
    Transcribe audio data.
    
    Accepts base64-encoded audio and returns transcription segments.
    """
    try:
        # Decode audio
        audio_bytes = base64.b64decode(data.audio_data)
        
        # Save to temp file (faster-whisper needs a file)
        with tempfile.NamedTemporaryFile(suffix=f".{data.format}", delete=False) as f:
            f.write(audio_bytes)
            temp_path = f.name
        
        try:
            # Run transcription in thread pool
            loop = asyncio.get_event_loop()
            transcriber = get_transcriber()
            
            segments = await loop.run_in_executor(
                executor,
                transcriber.transcribe_file,
                temp_path,
                data.language,
            )
            
            # Format response
            segment_dicts = [
                {
                    "text": seg.text,
                    "start": seg.start,
                    "end": seg.end,
                    "confidence": seg.confidence,
                }
                for seg in segments
            ]
            
            full_text = " ".join(seg.text for seg in segments)
            
            return TranscribeResponse(
                success=True,
                segments=segment_dicts,
                full_text=full_text,
                duration_seconds=segments[-1].end if segments else 0,
            )
            
        finally:
            # Clean up temp file
            os.unlink(temp_path)
            
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        return TranscribeResponse(
            success=False,
            error=str(e),
        )


# ==================== Notes Generation Endpoints ====================

@app.post("/api/v1/notes/generate", response_model=NotesResponse)
async def generate_notes(
    data: NotesRequest,
    request: Request,
    _=Depends(require_feature("notes"))
):
    """
    Generate meeting notes from transcript.
    
    Uses LLM to extract summary, key points, action items, etc.
    """
    try:
        loop = asyncio.get_event_loop()
        note_taker = get_note_taker()
        
        # Run LLM in thread pool
        notes = await loop.run_in_executor(
            executor,
            note_taker.generate_notes,
            data.transcript,
            data.context,
        )
        
        return NotesResponse(
            success=True,
            summary=notes.summary,
            key_points=notes.key_points,
            action_items=notes.action_items,
            decisions=notes.decisions,
            questions=notes.questions,
        )
        
    except Exception as e:
        logger.error(f"Note generation error: {e}")
        return NotesResponse(
            success=False,
            error=str(e),
        )


@app.post("/api/v1/notes/update", response_model=NotesResponse)
async def update_notes(
    data: NotesUpdateRequest,
    request: Request,
    _=Depends(require_feature("notes"))
):
    """
    Update existing notes with new transcript content.
    
    Incrementally adds new information to existing notes.
    """
    try:
        loop = asyncio.get_event_loop()
        note_taker = get_note_taker()
        
        # Reconstruct MeetingNotes from dict
        existing = MeetingNotes(
            summary=data.existing_notes.get("summary", ""),
            key_points=data.existing_notes.get("key_points", []),
            action_items=data.existing_notes.get("action_items", []),
            decisions=data.existing_notes.get("decisions", []),
            questions=data.existing_notes.get("questions", []),
        )
        
        # Run LLM in thread pool
        notes = await loop.run_in_executor(
            executor,
            note_taker.generate_incremental_notes,
            data.new_transcript,
            existing,
        )
        
        return NotesResponse(
            success=True,
            summary=notes.summary,
            key_points=notes.key_points,
            action_items=notes.action_items,
            decisions=notes.decisions,
            questions=notes.questions,
        )
        
    except Exception as e:
        logger.error(f"Note update error: {e}")
        return NotesResponse(
            success=False,
            error=str(e),
        )


# ==================== WebSocket Streaming ====================

@app.websocket("/api/v1/stream")
async def websocket_stream(websocket: WebSocket):
    """
    WebSocket endpoint for real-time transcription streaming.
    
    Protocol:
    - Client sends: {"type": "auth", "api_key": "..."}
    - Client sends: {"type": "audio", "data": "<base64>", "format": "webm"}
    - Server sends: {"type": "transcript", "text": "...", "timestamp": ...}
    - Server sends: {"type": "notes", ...}
    """
    await websocket.accept()
    
    # Wait for auth message
    try:
        auth_msg = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        
        if auth_msg.get("type") != "auth":
            await websocket.send_json({"type": "error", "message": "Expected auth message"})
            await websocket.close()
            return
        
        api_key = auth_msg.get("api_key", "")
        key_data = validate_api_key(api_key)
        
        if not key_data:
            await websocket.send_json({"type": "error", "message": "Invalid API key"})
            await websocket.close()
            return
        
        await websocket.send_json({
            "type": "auth_success",
            "tier": key_data.tier,
            "features": key_data.features,
        })
        
    except asyncio.TimeoutError:
        await websocket.send_json({"type": "error", "message": "Auth timeout"})
        await websocket.close()
        return
    
    # Store connection
    connection_id = f"{key_data.key_hash[:8]}_{int(time.time())}"
    state.active_streams[connection_id] = websocket
    
    logger.info(f"WebSocket connected: {connection_id}")
    
    # Accumulate transcript for notes
    full_transcript = ""
    current_notes = None
    last_notes_time = 0
    is_generating_notes = False
    
    # Track chunk count for calculating actual timestamps
    # Each chunk is ~3 seconds of audio
    chunk_count = 0
    chunk_duration = 3.0  # seconds per audio chunk
    
    try:
        while True:
            msg = await websocket.receive_json()
            msg_type = msg.get("type")
            
            if msg_type == "audio":
                # Transcribe audio chunk
                try:
                    audio_bytes = base64.b64decode(msg.get("data", ""))
                    audio_format = msg.get("format", "webm")
                    
                    with tempfile.NamedTemporaryFile(suffix=f".{audio_format}", delete=False) as f:
                        f.write(audio_bytes)
                        temp_path = f.name
                    
                    # Calculate time offset based on chunk number
                    time_offset = chunk_count * chunk_duration
                    
                    try:
                        loop = asyncio.get_event_loop()
                        transcriber = get_transcriber()
                        
                        segments = await loop.run_in_executor(
                            executor,
                            transcriber.transcribe_file,
                            temp_path,
                        )
                        
                        for seg in segments:
                            # Add time offset to get actual recording timestamp
                            actual_start = time_offset + seg.start
                            actual_end = time_offset + seg.end
                            
                            await websocket.send_json({
                                "type": "transcript",
                                "text": seg.text,
                                "start": actual_start,
                                "end": actual_end,
                            })
                            full_transcript += f" {seg.text}"
                        
                        # Increment chunk count after processing
                        chunk_count += 1
                        
                    finally:
                        os.unlink(temp_path)
                    
                    # Generate notes in background every 30 seconds
                    if time.time() - last_notes_time > 30 and len(full_transcript) > 100 and not is_generating_notes:
                        is_generating_notes = True
                        
                        # Create a task for note generation
                        async def generate_notes_task(transcript_snapshot, context_notes):
                            nonlocal current_notes, last_notes_time, is_generating_notes
                            try:
                                note_taker = get_note_taker()
                                loop = asyncio.get_event_loop()
                                
                                if context_notes is None:
                                    notes = await loop.run_in_executor(
                                        executor,
                                        note_taker.generate_notes,
                                        transcript_snapshot,
                                    )
                                else:
                                    # Calculate new text since last notes
                                    # Note: relying on raw_response to track covered text length
                                    start_idx = len(context_notes.raw_response) if hasattr(context_notes, 'raw_response') else 0
                                    new_text = transcript_snapshot[start_idx:]
                                    
                                    notes = await loop.run_in_executor(
                                        executor,
                                        note_taker.generate_incremental_notes,
                                        new_text,
                                        context_notes,
                                    )
                                
                                current_notes = notes
                                last_notes_time = time.time()
                                
                                await websocket.send_json({
                                    "type": "notes",
                                    "summary": notes.summary,
                                    "key_points": notes.key_points,
                                    "action_items": notes.action_items,
                                    "decisions": notes.decisions,
                                    "questions": notes.questions,
                                })
                                
                            except Exception as e:
                                logger.error(f"Background note generation error: {e}")
                                # Don't send error to client to avoid disrupting stream
                            finally:
                                is_generating_notes = False

                        asyncio.create_task(generate_notes_task(full_transcript, current_notes))

                except Exception as e:
                    logger.error(f"Stream processing error: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "message": str(e),
                    })
            
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            
            elif msg_type == "stop":
                # Generate final notes
                if full_transcript:
                    note_taker = get_note_taker()
                    loop = asyncio.get_event_loop()
                    
                    notes = await loop.run_in_executor(
                        executor,
                        note_taker.generate_notes,
                        full_transcript,
                    )
                    
                    await websocket.send_json({
                        "type": "final_notes",
                        "summary": notes.summary,
                        "key_points": notes.key_points,
                        "action_items": notes.action_items,
                        "decisions": notes.decisions,
                        "questions": notes.questions,
                        "transcript": full_transcript,
                    })
                break
                
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {connection_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        state.active_streams.pop(connection_id, None)


# ==================== Error Handlers ====================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "code": f"HTTP_{exc.status_code}"},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "code": "INTERNAL_ERROR"},
    )


if __name__ == "__main__":
    uvicorn.run(
        "api_server:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        log_level="info",
    )
