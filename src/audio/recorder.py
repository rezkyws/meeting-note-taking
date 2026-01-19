"""
AI Meeting Note Taker - Audio Recording Module

Captures system audio (loopback) for meeting transcription.
"""

import numpy as np
import soundcard as sc
import soundfile as sf
import threading
import queue
import time
from pathlib import Path
from typing import Optional, Callable


class SystemAudioRecorder:
    """Records audio from system output (loopback/monitor)."""

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_duration: float = 3.0,  # Reduced for faster response
        output_dir: Optional[Path] = None,
    ):
        """
        Initialize the audio recorder.

        Args:
            sample_rate: Audio sample rate in Hz (16000 recommended for Whisper).
            chunk_duration: Duration of each audio chunk in seconds.
            output_dir: Directory to save audio chunks (optional).
        """
        self.sample_rate = sample_rate
        self.chunk_duration = chunk_duration
        self.output_dir = output_dir or Path("./audio_chunks")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._is_recording = False
        self._audio_queue: queue.Queue = queue.Queue()
        self._record_thread: Optional[threading.Thread] = None
        self._speaker: Optional[sc.Speaker] = None

    def get_available_speakers(self) -> list[dict]:
        """Get list of available speaker/output devices."""
        speakers = sc.all_speakers()
        return [{"id": s.id, "name": s.name} for s in speakers]

    def get_default_speaker(self) -> Optional[dict]:
        """Get the default speaker device."""
        try:
            speaker = sc.default_speaker()
            return {"id": speaker.id, "name": speaker.name}
        except Exception:
            return None

    def start_recording(
        self,
        speaker_id: Optional[str] = None,
        on_chunk_ready: Optional[Callable[[np.ndarray, str], None]] = None,
    ) -> bool:
        """
        Start recording from system audio.

        Args:
            speaker_id: ID of speaker to record from. Uses default if None.
            on_chunk_ready: Callback when a chunk is ready. Args: (audio_data, filepath)

        Returns:
            True if recording started successfully.
        """
        if self._is_recording:
            return False

        try:
            if speaker_id:
                speakers = sc.all_speakers()
                self._speaker = next((s for s in speakers if s.id == speaker_id), None)
            else:
                self._speaker = sc.default_speaker()

            if not self._speaker:
                raise ValueError("No speaker device found")

            self._is_recording = True
            self._record_thread = threading.Thread(
                target=self._recording_loop,
                args=(on_chunk_ready,),
                daemon=True,
            )
            self._record_thread.start()
            return True

        except Exception as e:
            print(f"Failed to start recording: {e}")
            self._is_recording = False
            return False

    def stop_recording(self) -> None:
        """Stop the current recording session."""
        self._is_recording = False
        if self._record_thread:
            self._record_thread.join(timeout=2.0)
            self._record_thread = None

    def _recording_loop(
        self,
        on_chunk_ready: Optional[Callable[[np.ndarray, str], None]] = None,
    ) -> None:
        """Main recording loop running in a separate thread."""
        chunk_samples = int(self.sample_rate * self.chunk_duration)
        chunk_index = 0

        try:
            # Find a loopback microphone
            # On Linux, loopback mics are monitors of output devices
            loopback_mics = sc.all_microphones(include_loopback=True)
            
            # Try to find a loopback mic matching our speaker
            mic = None
            speaker_name = self._speaker.name.lower() if self._speaker else ""
            
            for m in loopback_mics:
                # Loopback mics often have "monitor" in name or match speaker name
                mic_name = m.name.lower()
                if m.isloopback:
                    # Prefer one matching our speaker
                    if speaker_name and speaker_name.split()[0] in mic_name:
                        mic = m
                        break
                    elif mic is None:
                        mic = m  # Fallback to first loopback
            
            if mic is None:
                raise ValueError(
                    "No loopback microphone found. "
                    "On Linux, ensure PulseAudio/PipeWire is running. "
                    f"Available mics: {[m.name for m in loopback_mics]}"
                )

            print(f"Using loopback device: {mic.name}")

            with mic.recorder(samplerate=self.sample_rate, channels=1) as recorder:
                while self._is_recording:
                    # Record chunk
                    audio_data = recorder.record(numframes=chunk_samples)

                    # Convert to mono if stereo
                    if len(audio_data.shape) > 1 and audio_data.shape[1] > 1:
                        audio_data = np.mean(audio_data, axis=1)
                    else:
                        audio_data = audio_data.flatten()

                    # Skip silent chunks (basic VAD) - lowered threshold
                    max_amplitude = np.max(np.abs(audio_data))
                    if max_amplitude < 0.005:
                        # print(f"Skipping silent chunk (max amp: {max_amplitude:.4f})")
                        continue

                    # print(f"Recording chunk {chunk_index} (max amp: {max_amplitude:.4f})")

                    # Save chunk
                    timestamp = int(time.time() * 1000)
                    filename = f"chunk_{chunk_index:04d}_{timestamp}.wav"
                    filepath = self.output_dir / filename

                    sf.write(str(filepath), audio_data, self.sample_rate)

                    # Add to queue and call callback
                    self._audio_queue.put((audio_data, str(filepath)))
                    if on_chunk_ready:
                        on_chunk_ready(audio_data, str(filepath))

                    chunk_index += 1

        except Exception as e:
            print(f"Recording error: {e}")
            self._is_recording = False

    def get_next_chunk(self, timeout: float = 1.0) -> Optional[tuple[np.ndarray, str]]:
        """
        Get the next audio chunk from the queue.

        Args:
            timeout: Timeout in seconds.

        Returns:
            Tuple of (audio_data, filepath) or None if queue is empty.
        """
        try:
            return self._audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    @property
    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._is_recording


# Simple test
if __name__ == "__main__":
    recorder = SystemAudioRecorder(chunk_duration=3.0)

    print("Available speakers:")
    for speaker in recorder.get_available_speakers():
        print(f"  - {speaker['name']} (ID: {speaker['id']})")

    print(f"\nDefault speaker: {recorder.get_default_speaker()}")

    print("\nRecording for 10 seconds...")
    recorder.start_recording()
    time.sleep(10)
    recorder.stop_recording()

    print(f"\nSaved chunks to: {recorder.output_dir}")
