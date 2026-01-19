"""
AI Meeting Note Taker - Transcription Engine

Uses faster-whisper for speech-to-text transcription.
"""

import numpy as np
from faster_whisper import WhisperModel
from pathlib import Path
from typing import Optional, Iterator
from dataclasses import dataclass


@dataclass
class TranscriptionSegment:
    """A single transcription segment with timing."""

    text: str
    start: float
    end: float
    confidence: float


class WhisperTranscriber:
    """Speech-to-text transcription using faster-whisper."""

    AVAILABLE_MODELS = [
        "tiny",
        "tiny.en",
        "base",
        "base.en",
        "small",
        "small.en",
        "medium",
        "medium.en",
        "large-v2",
        "large-v3",
    ]

    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",  # Default to CPU for compatibility
        compute_type: str = "int8",  # int8 is faster on CPU
    ):
        """
        Initialize the Whisper transcriber.

        Args:
            model_size: Whisper model size (tiny, base, small, medium, large-v3).
            device: Device to run on ("cpu", "cuda", "auto").
            compute_type: Compute type ("int8", "float16", "float32").
        """
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model: Optional[WhisperModel] = None

    def load_model(self) -> None:
        """Load the Whisper model into memory."""
        if self._model is None:
            print(f"Loading Whisper model: {self.model_size}...")
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
            print("Model loaded successfully.")

    def unload_model(self) -> None:
        """Unload the model from memory."""
        self._model = None

    def transcribe_file(
        self,
        audio_path: str | Path,
        language: Optional[str] = None,
    ) -> list[TranscriptionSegment]:
        """
        Transcribe an audio file.

        Args:
            audio_path: Path to the audio file.
            language: Language code (e.g., "en", "id"). Auto-detect if None.

        Returns:
            List of transcription segments.
        """
        self.load_model()

        segments, info = self._model.transcribe(
            str(audio_path),
            language=language,
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        results = []
        for segment in segments:
            results.append(
                TranscriptionSegment(
                    text=segment.text.strip(),
                    start=segment.start,
                    end=segment.end,
                    confidence=segment.avg_logprob,
                )
            )

        return results

    def transcribe_audio(
        self,
        audio_data: np.ndarray,
        sample_rate: int = 16000,
        language: Optional[str] = None,
    ) -> list[TranscriptionSegment]:
        """
        Transcribe audio data directly from numpy array.

        Args:
            audio_data: Audio samples as numpy array.
            sample_rate: Sample rate of the audio.
            language: Language code. Auto-detect if None.

        Returns:
            List of transcription segments.
        """
        self.load_model()

        # Ensure audio is float32 and normalized
        if audio_data.dtype != np.float32:
            audio_data = audio_data.astype(np.float32)

        if np.max(np.abs(audio_data)) > 1.0:
            audio_data = audio_data / np.max(np.abs(audio_data))

        segments, info = self._model.transcribe(
            audio_data,
            language=language,
            beam_size=5,
            vad_filter=True,
        )

        results = []
        for segment in segments:
            results.append(
                TranscriptionSegment(
                    text=segment.text.strip(),
                    start=segment.start,
                    end=segment.end,
                    confidence=segment.avg_logprob,
                )
            )

        return results

    def transcribe_stream(
        self,
        audio_path: str | Path,
        language: Optional[str] = None,
    ) -> Iterator[TranscriptionSegment]:
        """
        Stream transcription results as they become available.

        Args:
            audio_path: Path to the audio file.
            language: Language code. Auto-detect if None.

        Yields:
            TranscriptionSegment as they are processed.
        """
        self.load_model()

        segments, info = self._model.transcribe(
            str(audio_path),
            language=language,
            beam_size=5,
            vad_filter=True,
        )

        for segment in segments:
            yield TranscriptionSegment(
                text=segment.text.strip(),
                start=segment.start,
                end=segment.end,
                confidence=segment.avg_logprob,
            )

    @property
    def is_loaded(self) -> bool:
        """Check if model is loaded."""
        return self._model is not None


# Simple test
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python engine.py <audio_file>")
        sys.exit(1)

    transcriber = WhisperTranscriber(model_size="base")

    print(f"Transcribing: {sys.argv[1]}")
    segments = transcriber.transcribe_file(sys.argv[1])

    print("\n--- Transcription ---")
    for seg in segments:
        print(f"[{seg.start:.2f}s - {seg.end:.2f}s] {seg.text}")
