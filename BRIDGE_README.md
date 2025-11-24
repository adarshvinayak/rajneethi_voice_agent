# Plivo-LiveKit Bridge Server

Bridge server that connects Plivo outbound calls to LiveKit rooms for AI agent handling.

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment variables in `.env`:**
   ```bash
   # LiveKit Configuration
   LIVEKIT_URL=wss://your-project.livekit.cloud
   LIVEKIT_API_KEY=your_livekit_api_key
   LIVEKIT_API_SECRET=your_livekit_api_secret

   # Plivo Configuration
   PLIVO_AUTH_ID=your_plivo_auth_id
   PLIVO_AUTH_TOKEN=your_plivo_auth_token
   PLIVO_PHONE_NUMBER=+1234567890  # Your Plivo number in E.164 format

   # Bridge Server URL (ngrok or public URL)
   BRIDGE_SERVER_URL=https://calamitous-jill-afflictively.ngrok-free.dev
   ```

3. **Start ngrok (if not already running):**
   ```bash
   ngrok http 8000
   ```
   Update `BRIDGE_SERVER_URL` in `.env` with your ngrok URL.

4. **Configure Plivo Application:**
   - Go to Plivo Console → Applications
   - Set Answer URL to: `{BRIDGE_SERVER_URL}/plivo/answer`
   - Set Answer Method: `POST`

5. **Start the bridge server:**
   ```bash
   python plivo_bridge.py
   ```

6. **Start the agent (in a separate terminal):**
   ```bash
   python agent.py dev
   ```

## Making Calls

### Using the API:
```bash
python make_call.py +1234567890
```

### Using curl:
```bash
curl -X POST https://calamitous-jill-afflictively.ngrok-free.dev/api/make_call \
  -H "Content-Type: application/json" \
  -d '{"to_number": "+1234567890"}'
```

## How It Works

1. **Call Initiation:**
   - Bridge server receives call request via `/api/make_call`
   - Makes outbound call via Plivo API
   - Plivo dials the customer number

2. **Call Answer:**
   - When customer answers, Plivo calls `/plivo/answer` webhook
   - Bridge returns XML with `<Stream>` element
   - Plivo opens WebSocket connection to `/plivo/media-stream`

3. **Audio Streaming:**
   - Bridge creates LiveKit room: `plivo-call-{call_uuid}`
   - Connects to LiveKit room
   - Streams audio bidirectionally:
     - **Plivo → LiveKit:** 16kHz L16 → resample to 48kHz → LiveKit
     - **LiveKit → Plivo:** 48kHz → resample to 16kHz → Plivo

4. **Agent Joins:**
   - Agent automatically joins the LiveKit room
   - Conversation begins!

## API Endpoints

- `POST /api/make_call` - Make an outbound call
  ```json
  {
    "to_number": "+1234567890"
  }
  ```

- `GET /api/get_call_metadata/{call_uuid}` - Get call metadata

- `POST /plivo/answer` - Plivo webhook (called when call is answered)

- `WebSocket /plivo/media-stream` - Audio streaming endpoint

- `GET /health` - Health check

## Testing

1. Start the bridge server
2. Start the agent
3. Make a test call:
   ```bash
   python make_call.py +1234567890
   ```
4. Answer the call - agent should join automatically!

## Troubleshooting

- **No audio:** Check that both bridge server and agent are running
- **Call not connecting:** Verify `BRIDGE_SERVER_URL` is correct and accessible
- **Agent not joining:** Check LiveKit credentials and room name format
- **WebSocket errors:** Ensure ngrok is running and URL is updated










