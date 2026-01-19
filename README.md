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

4. **Live notes update automatically** every ~30 seconds during recording - no need to wait until the end!

5. Click **Stop Recording** when done to generate comprehensive final notes

6. Download transcript and notes using the export buttons

## Features

- **Real-time transcription** - See what's being said as it happens
- **Live incremental notes** - AI-generated notes update every 30 seconds during the meeting
- **Non-blocking architecture** - Note generation runs asynchronously, never interrupting transcription
- **Final summary** - Comprehensive notes generated when recording stops
- **Export options** - Download transcript (.txt) and notes (.md)

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
