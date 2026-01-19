"""
AI Meeting Note Taker - FastAPI Backend

Real-time meeting transcription with WebSocket support.
"""

import asyncio
import json
import time
import concurrent.futures
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
import uvicorn

from src.audio.recorder import SystemAudioRecorder
from src.transcription.engine import WhisperTranscriber
from src.llm.note_taker import NoteTaker, MeetingNotes


# Thread pool for running blocking LLM calls
llm_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="llm")

# Global state
class AppState:
    def __init__(self):
        self.recorder: Optional[SystemAudioRecorder] = None
        self.transcriber: Optional[WhisperTranscriber] = None
        self.note_taker: Optional[NoteTaker] = None
        self.is_recording = False
        self.transcript: list[str] = []
        self.full_transcript = ""
        self.processed_chunks: set[str] = set()
        self.active_websockets: list[WebSocket] = []
        self.transcription_task: Optional[asyncio.Task] = None
        # Incremental notes state
        self.note_generation_task: Optional[asyncio.Task] = None
        self.current_notes: Optional[MeetingNotes] = None
        self.last_processed_transcript_len = 0
        self.note_generation_lock = asyncio.Lock()


state = AppState()


def get_recorder() -> SystemAudioRecorder:
    if state.recorder is None:
        state.recorder = SystemAudioRecorder(
            sample_rate=16000,
            chunk_duration=3.0,  # Reduced for faster response
            output_dir=Path("./recordings"),
        )
    return state.recorder


def get_transcriber() -> WhisperTranscriber:
    if state.transcriber is None:
        # Use 'tiny' for fastest transcription, 'base' for better accuracy
        state.transcriber = WhisperTranscriber(model_size="base")
    return state.transcriber


def get_note_taker() -> NoteTaker:
    if state.note_taker is None:
        state.note_taker = NoteTaker()
    return state.note_taker


async def broadcast(message: dict):
    """Send message to all connected WebSocket clients."""
    disconnected = []
    for ws in state.active_websockets:
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.append(ws)
    
    for ws in disconnected:
        state.active_websockets.remove(ws)


async def transcription_loop():
    """Background task that processes audio chunks and sends transcriptions."""
    recorder = get_recorder()
    transcriber = get_transcriber()
    chunk_duration = recorder.chunk_duration  # Get the chunk duration (e.g., 3.0 seconds)
    chunk_count = 0  # Track number of processed chunks for timestamp calculation
    
    # Load model
    await broadcast({"type": "status", "message": "Loading Whisper model..."})
    transcriber.load_model()
    await broadcast({"type": "status", "message": "Model loaded. Recording..."})
    
    while state.is_recording:
        # Check for new chunks (non-blocking)
        chunk_result = recorder.get_next_chunk(timeout=0.5)
        
        if chunk_result is not None:
            audio_data, filepath = chunk_result
            
            if filepath not in state.processed_chunks:
                state.processed_chunks.add(filepath)
                
                # Calculate time offset based on chunk number
                time_offset = chunk_count * chunk_duration
                chunk_count += 1
                
                # Transcribe (this blocks but runs in background)
                try:
                    segments = transcriber.transcribe_file(filepath)
                    
                    for seg in segments:
                        text = seg.text.strip()
                        if text:
                            # Add time offset to get actual recording timestamp
                            actual_timestamp = time_offset + seg.start
                            timestamp = f"[{actual_timestamp:.1f}s]"
                            line = f"{timestamp} {text}"
                            state.transcript.append(line)
                            state.full_transcript += f" {text}"
                            
                            # Send to all clients immediately
                            await broadcast({
                                "type": "transcript",
                                "text": text,
                                "timestamp": actual_timestamp,
                            })
                except Exception as e:
                    print(f"Transcription error: {e}")
        
        await asyncio.sleep(0.1)


async def note_generation_loop():
    """Background task that generates incremental notes without blocking transcription.
    
    Uses debouncing: generates notes every 30 seconds OR after 5 new transcript lines,
    whichever comes first. Runs LLM calls in a thread pool to not block the event loop.
    """
    note_taker = get_note_taker()
    last_generation_time = time.time()
    
    # Configuration
    MIN_INTERVAL_SECONDS = 30  # Minimum time between note generations
    MIN_NEW_LINES = 5  # Minimum new lines before considering generation
    MIN_TRANSCRIPT_LENGTH = 50  # Minimum chars before first generation
    
    await asyncio.sleep(10)  # Initial delay to accumulate some transcript
    
    while state.is_recording:
        try:
            current_transcript_len = len(state.full_transcript)
            new_content_len = current_transcript_len - state.last_processed_transcript_len
            new_lines_count = len(state.transcript) - (state.last_processed_transcript_len // 50)  # Rough estimate
            time_since_last = time.time() - last_generation_time
            
            # Check if we should generate notes
            should_generate = (
                current_transcript_len >= MIN_TRANSCRIPT_LENGTH and
                new_content_len > 0 and
                (time_since_last >= MIN_INTERVAL_SECONDS or new_lines_count >= MIN_NEW_LINES)
            )
            
            if should_generate:
                async with state.note_generation_lock:
                    await broadcast({
                        "type": "status", 
                        "message": "Updating notes..."
                    })
                    
                    # Get the new transcript segment
                    full_transcript = state.full_transcript
                    
                    # Run blocking LLM call in thread pool to not block event loop
                    loop = asyncio.get_event_loop()
                    
                    if state.current_notes is None:
                        # First time: generate initial notes
                        notes = await loop.run_in_executor(
                            llm_executor,
                            note_taker.generate_notes,
                            full_transcript
                        )
                    else:
                        # Incremental update with new content
                        new_transcript = full_transcript[state.last_processed_transcript_len:]
                        notes = await loop.run_in_executor(
                            llm_executor,
                            note_taker.generate_incremental_notes,
                            new_transcript,
                            state.current_notes
                        )
                    
                    # Update state
                    state.current_notes = notes
                    state.last_processed_transcript_len = len(full_transcript)
                    last_generation_time = time.time()
                    
                    # Broadcast incremental notes to clients
                    await broadcast({
                        "type": "incremental_notes",
                        "summary": notes.summary,
                        "key_points": notes.key_points,
                        "action_items": notes.action_items,
                        "decisions": notes.decisions,
                        "questions": notes.questions,
                    })
                    
                    await broadcast({
                        "type": "status", 
                        "message": "Notes updated. Recording..."
                    })
                    
        except Exception as e:
            print(f"Note generation error: {e}")
            await broadcast({
                "type": "status", 
                "message": f"Note update failed: {str(e)[:50]}"
            })
        
        await asyncio.sleep(5)  # Check every 5 seconds


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    print("AI Meeting Note Taker starting...")
    yield
    # Cleanup
    if state.is_recording:
        state.is_recording = False
        if state.recorder:
            state.recorder.stop_recording()
    print("Shutting down...")


app = FastAPI(title="AI Meeting Note Taker", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main page."""
    return FileResponse("static/index.html")


@app.get("/api/speakers")
async def get_speakers():
    """Get available audio devices."""
    recorder = get_recorder()
    return {
        "speakers": recorder.get_available_speakers(),
        "default": recorder.get_default_speaker(),
    }


@app.post("/api/start")
async def start_recording():
    """Start recording."""
    if state.is_recording:
        return {"error": "Already recording"}
    
    recorder = get_recorder()
    success = recorder.start_recording(on_chunk_ready=None)
    
    if success:
        state.is_recording = True
        state.transcript = []
        state.full_transcript = ""
        state.processed_chunks = set()
        # Reset incremental notes state
        state.current_notes = None
        state.last_processed_transcript_len = 0
        
        # Start transcription loop
        state.transcription_task = asyncio.create_task(transcription_loop())
        # Start background note generation (non-blocking)
        state.note_generation_task = asyncio.create_task(note_generation_loop())
        
        return {"status": "started"}
    else:
        return {"error": "Failed to start recording"}


@app.post("/api/stop")
async def stop_recording():
    """Stop recording and generate notes."""
    if not state.is_recording:
        return {"error": "Not recording"}
    
    state.is_recording = False
    recorder = get_recorder()
    recorder.stop_recording()
    
    # Wait for transcription task to finish
    if state.transcription_task:
        try:
            await asyncio.wait_for(state.transcription_task, timeout=5.0)
        except asyncio.TimeoutError:
            state.transcription_task.cancel()
    
    # Wait for note generation task to finish
    if state.note_generation_task:
        try:
            await asyncio.wait_for(state.note_generation_task, timeout=2.0)
        except asyncio.TimeoutError:
            state.note_generation_task.cancel()
    
    await broadcast({"type": "status", "message": "Recording stopped. Finalizing notes..."})
    
    # Smart final update: only process new content or use existing notes
    notes = None
    if state.full_transcript.strip():
        try:
            note_taker = get_note_taker()
            new_content_len = len(state.full_transcript) - state.last_processed_transcript_len
            
            if state.current_notes is None:
                # No existing notes - generate from scratch
                await broadcast({"type": "status", "message": "Generating notes..."})
                loop = asyncio.get_event_loop()
                notes = await loop.run_in_executor(
                    llm_executor,
                    note_taker.generate_notes,
                    state.full_transcript
                )
            elif new_content_len > 20:  # Only update if meaningful new content (>20 chars)
                # Has new content since last update - do final incremental update
                await broadcast({"type": "status", "message": "Updating notes with final content..."})
                new_transcript = state.full_transcript[state.last_processed_transcript_len:]
                loop = asyncio.get_event_loop()
                notes = await loop.run_in_executor(
                    llm_executor,
                    note_taker.generate_incremental_notes,
                    new_transcript,
                    state.current_notes
                )
            else:
                # Notes are up-to-date - use existing
                notes = state.current_notes
                await broadcast({"type": "status", "message": "Notes ready!"})
            
            await broadcast({
                "type": "notes",
                "summary": notes.summary,
                "key_points": notes.key_points,
                "action_items": notes.action_items,
                "decisions": notes.decisions,
                "questions": notes.questions,
            })
        except Exception as e:
            await broadcast({"type": "error", "message": f"Note generation failed: {e}"})
    
    return {
        "status": "stopped",
        "transcript": state.full_transcript,
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time updates."""
    await websocket.accept()
    state.active_websockets.append(websocket)
    
    # Send current state
    await websocket.send_json({
        "type": "init",
        "is_recording": state.is_recording,
        "transcript": state.transcript,
    })
    
    try:
        while True:
            # Keep connection alive, handle client messages
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    
    except WebSocketDisconnect:
        state.active_websockets.remove(websocket)


# Mount static files
Path("static").mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
