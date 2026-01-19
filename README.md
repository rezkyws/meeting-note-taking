# AI Meeting Note Taker

An AI-powered system that captures system audio during meetings, transcribes it in real-time using Whisper, and generates structured meeting notes using an LLM.

## Requirements

- Python 3.10+
- Linux with PulseAudio or PipeWire
- NVIDIA GPU (optional, for faster transcription)

## Installation

1. Clone and setup virtual environment:
   ```bash
   cd ai-noter
   python -m venv venv
   source venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure environment:
   ```bash
   cp .env.example .env
   # Edit .env and add your OpenAI API key (or use local LLM)
   ```

## Usage

1. Start the server:
   ```bash
   python server.py
   ```

2. Open your browser to `http://localhost:8000`

3. Click **Start Recording** and join your meeting

4. Click **Stop Recording** when done to generate final notes

5. Download transcript and notes using the export buttons

## Project Structure

```
ai-noter/
├── server.py               # FastAPI server with WebSocket support
├── requirements.txt        # Python dependencies
├── .env.example            # Environment template
├── static/
│   └── index.html          # Web UI
└── src/
    ├── audio/
    │   └── recorder.py     # System audio capture (loopback)
    ├── transcription/
    │   └── engine.py       # Whisper transcription engine
    └── llm/
        └── note_taker.py   # LLM-powered note generation
```

## Configuration

### Using Local LLMs (Ollama)

1. Install [Ollama](https://ollama.ai)
2. Pull a model: `ollama pull llama3`
3. Set in `.env`:
   ```
   OPENAI_BASE_URL=http://localhost:11434/v1
   ```

## API Endpoints

| Endpoint      | Method | Description                    |
|---------------|--------|--------------------------------|
| `/`           | GET    | Main web UI                    |
| `/api/speakers` | GET  | List available audio devices   |
| `/api/start`  | POST   | Start recording                |
| `/api/stop`   | POST   | Stop recording & generate notes|
| `/ws`         | WS     | WebSocket for real-time updates|

## License

MIT
