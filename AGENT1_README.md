# Agent1.py - ElevenLabs TTS Integration

## Overview

`agent1.py` is a new agent implementation that uses **ElevenLabs** for Text-to-Speech (TTS) instead of Cartesia, while keeping:
- **Deepgram** for Speech-to-Text (STT)
- **OpenAI** for Large Language Model (LLM)

## Configuration

### Environment Variables

Add these to your `.env` file:

```env
# ElevenLabs Configuration
ELEVENLABS_API_KEY=sk_c9b7e489065b8d5fe8ca162afc67d68b7b7c4c278830dac0
ELEVENLABS_VOICE_ID=wlmwDR77ptH6bKHZui0l

# Deepgram (already configured)
DEEPGRAM_API_KEY=your_deepgram_key

# OpenAI (already configured)
OPENAI_API_KEY=your_openai_key
```

### Dependencies

Install required packages:

```bash
pip install httpx pydub
```

**Note:** `pydub` requires `ffmpeg` to be installed on your system:
- **Windows**: Download from https://ffmpeg.org/download.html
- **Linux**: `sudo apt-get install ffmpeg`
- **macOS**: `brew install ffmpeg`

## Features

- ✅ **ElevenLabs TTS**: Uses ElevenLabs API for high-quality voice synthesis
- ✅ **MP3 to PCM Conversion**: Automatically converts ElevenLabs MP3 output to PCM16 format (48kHz mono) required by LiveKit
- ✅ **Streaming Audio**: Yields audio in chunks for low latency
- ✅ **Same Agent Logic**: Uses the same instructions and behavior as `agent.py`
- ✅ **Interruptions Enabled**: Smart resume when user interrupts

## Usage

Run the agent:

```bash
python agent1.py dev
```

Or deploy to LiveKit Cloud:

```bash
lk agent deploy
```

## Differences from agent.py

| Feature | agent.py | agent1.py |
|---------|----------|-----------|
| TTS Provider | Cartesia Sonic-3 | ElevenLabs |
| Voice | Palak (Indian accent) | Custom voice (wlmwDR77ptH6bKHZui0l) |
| Audio Format | Native PCM | MP3 → PCM conversion |
| Dependencies | Standard | Requires pydub + ffmpeg |

## Troubleshooting

### Error: "pydub not available"
**Solution**: Install pydub: `pip install pydub`

### Error: "ffmpeg not found"
**Solution**: Install ffmpeg system dependency (see above)

### Audio not playing
**Solution**: Check that:
1. ElevenLabs API key is correct
2. Voice ID is valid
3. Network connection is working
4. ffmpeg is installed and accessible

## Testing

Test the ElevenLabs API directly:

```powershell
$headers = @{"xi-api-key" = "sk_c9b7e489065b8d5fe8ca162afc67d68b7b7c4c278830dac0"; "Content-Type" = "application/json"}
$body = '{"text":"hello"}'
$response = Invoke-WebRequest -Uri "https://api.elevenlabs.io/v1/text-to-speech/wlmwDR77ptH6bKHZui0l" -Method POST -Headers $headers -Body $body
[System.IO.File]::WriteAllBytes("test_audio.mp3", $response.Content)
```

## Notes

- The custom TTS implementation converts ElevenLabs MP3 output to PCM16 format
- Audio is streamed in 8KB chunks for low latency
- If pydub is not available, the agent will attempt to use raw MP3 (may not work correctly)
- The voice ID `wlmwDR77ptH6bKHZui0l` is hardcoded but can be changed via environment variable

