# LiveKit Rajneethi AI Voice Agent

This project implements an AI Voice Agent capable of handling outbound calls via Plivo, connecting them to a LiveKit room where an AI agent (powered by OpenAI, Deepgram, and Cartesia) conducts a survey.

## Technology Stack & Tools

*   **[LiveKit](https://livekit.io/)**: Real-time audio/video infrastructure. It acts as the central hub where the AI agent and the phone caller (via Plivo) meet.
*   **[Plivo](https://www.plivo.com/)**: Cloud telephony provider. Handles the actual PSTN (Public Switched Telephone Network) phone calls. We use Plivo's "Media Streams" to stream raw audio from the phone call to our server.
*   **[OpenAI (GPT-4o-mini)](https://openai.com/)**: Large Language Model (LLM). The "brain" of the agent. It generates responses based on the conversation context.
*   **[Deepgram (Nova-2)](https://deepgram.com/)**: Speech-to-Text (STT). Converts the user's spoken Hindi/English audio into text for the LLM.
*   **[Cartesia (Sonic-3)](https://cartesia.ai/)**: Text-to-Speech (TTS). Converts the LLM's text response into natural-sounding Hindi speech (Voice: Palak).
*   **[Silero VAD](https://github.com/snakers4/silero-vad)**: Voice Activity Detection. Detects when the user starts and stops speaking to manage turn-taking naturally.

---

## Module Breakdown

### 1. `agent.py` (The AI Agent)
This script runs the AI worker that connects to a LiveKit room and interacts with the participant.

*   **Role**: The "Brain" and "Voice" of the system.
*   **Key Components**:
    *   **`prewarm(proc)`**: Preloads models (specifically Silero VAD) to ensure zero latency when a call starts.
    *   **`entrypoint(ctx)`**: The main logic loop.
        *   **Connection**: Connects to the LiveKit room.
        *   **Agent Initialization**: Configures the `VoicePipelineAgent` with:
            *   **VAD**: Silero (configured to wait for user to finish speaking).
            *   **STT**: Deepgram (Hindi, Nova-2).
            *   **LLM**: OpenAI (GPT-4o-mini) with specific system instructions ("Nisha", the reporter).
            *   **TTS**: Cartesia (Hindi, Palak).
        *   **Event Handlers**: Logs events like user speech start/end, transcription commits, etc.
        *   **Instant Greeting**: Uses a background task to say "Hello" immediately (<1s) upon connection, masking any initialization delay.

### 2. `plivo_bridge.py` (The SIP Bridge)
This script is a FastAPI server that acts as a bridge between the traditional phone network (Plivo) and the modern WebRTC world (LiveKit).

*   **Role**: The "Translator" and "Router".
*   **Key Components**:
    *   **`/api/make_call`**: Endpoint to trigger an outbound call. It tells Plivo to call a number and points the "Answer URL" to this server.
    *   **`/plivo/answer`**: Webhook called by Plivo when the user picks up. It returns XML instructing Plivo to open a WebSocket connection (`<Stream>`).
    *   **`/plivo/media-stream` (WebSocket)**: The core bridge logic.
        *   **Room Creation**: Creates a unique LiveKit room for the call (`plivo-call-{uuid}`).
        *   **Audio Relay (Plivo -> LiveKit)**: Receives 16kHz audio from Plivo, upsamples it to 48kHz, and publishes it to the LiveKit room so the AI agent can hear it.
        *   **Audio Relay (LiveKit -> Plivo)**: Subscribes to the AI agent's audio track, downsamples it from 48kHz to 16kHz, and sends it to Plivo so the user can hear the AI.

---

## End-to-End Call Flow

Here is how a complete interaction works from start to finish:

1.  **Trigger Call**:
    *   You send a POST request to `http://localhost:8000/api/make_call` with a `to_number`.
    *   `plivo_bridge.py` uses the Plivo API to initiate a phone call to that number.

2.  **User Answers**:
    *   The user picks up the phone.
    *   Plivo requests the "Answer URL" (`/plivo/answer`) from `plivo_bridge.py`.
    *   The bridge returns XML telling Plivo to start a **Media Stream** (WebSocket) to `/plivo/media-stream`.

3.  **Bridge Connection**:
    *   Plivo opens a WebSocket connection to `plivo_bridge.py`.
    *   The bridge creates a new **LiveKit Room** (e.g., `plivo-call-12345`).
    *   The bridge joins this room as a participant ("Plivo Bridge").

4.  **Agent Joins**:
    *   The `agent.py` worker (listening for new rooms) detects the new room.
    *   It joins the room as the "Agent".
    *   It immediately triggers the "Instant Greeting" ("Hello...").

5.  **Conversation Loop**:
    *   **User Speaks**:
        *   Audio goes: Phone -> Plivo -> Bridge (WebSocket) -> Upsample -> LiveKit Room.
        *   `agent.py` hears the audio via LiveKit.
        *   **Deepgram** transcribes it to text.
        *   **OpenAI** generates a response based on the "Nisha" persona.
        *   **Cartesia** converts the response to audio.
    *   **Agent Speaks**:
        *   Audio goes: `agent.py` -> LiveKit Room.
        *   Bridge hears the audio via LiveKit.
        *   Bridge downsamples it -> WebSocket -> Plivo -> Phone.
        *   User hears the AI response.

6.  **Termination**:
    *   When the call ends, Plivo closes the WebSocket.
    *   The bridge disconnects from the LiveKit room.
    *   The agent detects the participant left and shuts down.
