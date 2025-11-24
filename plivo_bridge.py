"""
Plivo to LiveKit Bridge Server
Makes outbound calls via Plivo Media Streams and connects them to LiveKit rooms
Based on the reference implementation from livekit-exotel
"""
import os
import asyncio
import logging
import uuid
import base64
import numpy as np
from typing import Optional, Dict, Any
from collections import deque
from dotenv import load_dotenv

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response, PlainTextResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from livekit import api, rtc
import plivo
import phonenumbers
from phonenumbers import NumberParseException

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("plivo-bridge")

# Configuration
LIVEKIT_URL = os.getenv("LIVEKIT_URL")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")
BRIDGE_SERVER_URL = os.getenv("BRIDGE_SERVER_URL", "https://your-ngrok-url.ngrok-free.app")
PLIVO_PHONE_NUMBER = os.getenv("PLIVO_PHONE_NUMBER")
PLIVO_AUTH_ID = os.getenv("PLIVO_AUTH_ID")
PLIVO_AUTH_TOKEN = os.getenv("PLIVO_AUTH_TOKEN")

app = FastAPI(title="Plivo-LiveKit Bridge Server")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active sessions
active_sessions = {}
call_metadata = {}

# LiveKit API client (initialized lazily to avoid event loop issues)
_livekit_client = None

def get_livekit_client():
    """Get or create LiveKit API client (lazy initialization)"""
    global _livekit_client
    if _livekit_client is None and all([LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET]):
        _livekit_client = api.LiveKitAPI(
            url=LIVEKIT_URL,
            api_key=LIVEKIT_API_KEY,
            api_secret=LIVEKIT_API_SECRET
        )
    return _livekit_client

# Initialize Plivo client
plivo_client = None
if all([PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN]):
    plivo_client = plivo.RestClient(PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN)


class PlivoService:
    """Service for making Plivo calls"""
    
    def __init__(self):
        if not all([PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN, PLIVO_PHONE_NUMBER]):
            raise ValueError("Missing Plivo credentials. Set PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN, and PLIVO_PHONE_NUMBER")
        self.client = plivo.RestClient(PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN)
        self.phone_number = PLIVO_PHONE_NUMBER
    
    def validate_phone_number(self, phone_number: str) -> tuple[bool, str]:
        """Validate and format phone number"""
        try:
            parsed = phonenumbers.parse(phone_number, None)
            if not phonenumbers.is_valid_number(parsed):
                return False, "Invalid phone number"
            formatted = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
            return True, formatted
        except NumberParseException as e:
            return False, f"Phone number parsing error: {str(e)}"
    
    def make_call(self, to_number: str, answer_url: Optional[str] = None) -> Dict[str, Any]:
        """Make an outbound call via Plivo"""
        # Validate phone number
        is_valid, result = self.validate_phone_number(to_number)
        if not is_valid:
            return {"success": False, "error": result}
        
        formatted_number = result
        
        # Get answer URL
        if not answer_url:
            answer_url = f"{BRIDGE_SERVER_URL}/plivo/answer"
        
        try:
            logger.info(f"Making call from {self.phone_number} to {formatted_number}")
            
            response = self.client.calls.create(
                from_=self.phone_number,
                to_=formatted_number,
                answer_url=answer_url,
                answer_method='POST',
            )
            
            call_uuid = response.request_uuid
            
            logger.info(f"Call initiated: {call_uuid}")
            
            return {
                "success": True,
                "call_uuid": call_uuid,
                "message": response.message
            }
        except Exception as e:
            logger.error(f"Failed to make call: {e}")
            return {"success": False, "error": str(e)}


def get_plivo_service() -> PlivoService:
    """Get or create Plivo service instance"""
    return PlivoService()


@app.post("/answer")
async def handle_plivo_answer_short(request: Request):
    """Short answer URL endpoint (for Plivo configuration)"""
    return await handle_plivo_answer(request)


@app.post("/plivo/answer")
async def handle_plivo_answer(request: Request):
    """
    Webhook for Plivo when call is answered.
    Returns XML with Stream element to establish WebSocket connection.
    """
    try:
        form_data = await request.form()
        call_uuid = form_data.get("CallUUID", "unknown")
        from_number = form_data.get("From", "unknown")
        to_number = form_data.get("To", "unknown")
        
        logger.info("=" * 70)
        logger.info("[PLIVO ANSWER] Call received")
        logger.info(f"Call UUID: {call_uuid}")
        logger.info(f"From: {from_number}")
        logger.info(f"To: {to_number}")
        logger.info("=" * 70)
        
        # Construct WebSocket URL for media streaming
        ws_protocol = "wss" if BRIDGE_SERVER_URL.startswith("https://") else "ws"
        ws_url = BRIDGE_SERVER_URL.replace("https://", "").replace("http://", "")
        media_stream_url = f"{ws_protocol}://{ws_url}/plivo/media-stream"
        
        logger.info(f"Media Stream URL: {media_stream_url}")
        
        # Return Plivo XML with Stream element
        # L16 format: 16kHz Linear PCM, bidirectional audio
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Stream bidirectional="true" keepCallAlive="true" audioTrack="inbound" contentType="audio/x-l16;rate=16000">{media_stream_url}</Stream>
</Response>"""
        
        logger.info("Returning XML response to Plivo")
        return Response(content=xml, media_type="application/xml")
    
    except Exception as e:
        logger.error(f"[PLIVO ANSWER ERROR] {e}", exc_info=True)
        # Return a basic XML response even on error to prevent call failure
        error_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak>Error connecting to bridge server</Speak>
</Response>"""
        return Response(content=error_xml, media_type="application/xml", status_code=200)


@app.websocket("/plivo/media-stream")
async def media_stream_handler(websocket: WebSocket):
    """
    WebSocket endpoint for Plivo Media Streams.
    Handles bidirectional audio between Plivo and LiveKit.
    """
    await websocket.accept()
    
    call_uuid = None
    room = None
    audio_source = None
    session_id = None
    
    try:
        logger.info("=" * 70)
        logger.info("[WEBSOCKET] Plivo Media Stream connected")
        logger.info("=" * 70)
        
        # Receive start message from Plivo
        data = await websocket.receive_json()
        logger.info(f"[WS] Received message from Plivo: {data}")
        event_type = data.get("event")
        
        if event_type == "start":
            # Plivo Media Streams sends start event with nested start data
            start_data = data.get("start", {})
            
            # Extract call UUID from start data (Plivo uses "callId")
            call_uuid = (
                start_data.get("callId") or
                start_data.get("callID") or
                start_data.get("callUuid") or
                start_data.get("callUUID") or
                data.get("callUUID") or
                data.get("call_uuid")
            )
            
            stream_sid = start_data.get("streamId") or start_data.get("streamSid")
            session_id = stream_sid or call_uuid or f"plivo-{id(websocket)}"
            
            logger.info(f"Call UUID: {call_uuid}")
            logger.info(f"Stream SID: {stream_sid}")
            logger.info(f"Session ID: {session_id}")
            
            # Create LiveKit room
            room_name = f"plivo-call-{call_uuid}"
            
            livekit_client = get_livekit_client()
            if livekit_client:
                room_info = livekit_client.room.create_room(
                    api.CreateRoomRequest(name=room_name)
                )
                logger.info(f"Created LiveKit room: {room_name}")
            else:
                logger.error("LiveKit client not initialized - check LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET")
                return
            
            # Connect to LiveKit room
            token = api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET) \
                .with_identity("plivo-bridge") \
                .with_name("Plivo Bridge") \
                .with_grants(api.VideoGrants(
                    room_join=True,
                    room=room_name,
                    can_publish=True,
                    can_subscribe=True,
                )).to_jwt()
            
            # Create Room instance first, then connect
            room = rtc.Room()
            await room.connect(LIVEKIT_URL, token)
            logger.info(f"Connected to LiveKit room: {room_name}")
            
            # Create audio source for sending Plivo audio to LiveKit
            # LiveKit uses 48kHz, Plivo sends 16kHz - we'll upsample
            audio_source = rtc.AudioSource(sample_rate=48000, num_channels=1)
            track = rtc.LocalAudioTrack.create_audio_track("phone_audio", audio_source)
            options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
            await room.local_participant.publish_track(track, options)
            
            logger.info("Published audio track to LiveKit")
            
            # Create resamplers for audio conversion with BETTER quality to avoid distortion
            resampler_16k_to_48k = rtc.AudioResampler(
                input_rate=16000,
                output_rate=48000,
                num_channels=1,
                quality=rtc.AudioResamplerQuality.HIGH  # Better quality
            )
            resampler_48k_to_16k = rtc.AudioResampler(
                input_rate=48000,
                output_rate=16000,
                num_channels=1,
                quality=rtc.AudioResamplerQuality.HIGH  # Better quality
            )
            
            # Store session
            active_sessions[session_id] = {
                "call_uuid": call_uuid,
                "room": room,
                "audio_source": audio_source,
                "websocket": websocket,
                "resampler_16k_to_48k": resampler_16k_to_48k,
                "resampler_48k_to_16k": resampler_48k_to_16k
            }
            
            # Handle incoming audio from Plivo -> LiveKit
            async def handle_plivo_audio():
                try:
                    logger.info("[PLIVO AUDIO] Starting to listen for audio from Plivo...")
                    while True:
                        message = await websocket.receive_json()
                        event = message.get("event")
                        
                        # Only log non-media events to reduce noise
                        if event != "media":
                            logger.info(f"[WS] Plivo event: {event}")
                        
                        if event == "media":
                            # Receive audio from Plivo (L16 format, base64 encoded, 16kHz)
                            # Log first media message to see structure
                            if not hasattr(handle_plivo_audio, "_logged_media"):
                                logger.info(f"[DEBUG] First media message structure: {message}")
                                handle_plivo_audio._logged_media = True
                            
                            payload = message.get("payload") or message.get("media", {}).get("payload")
                            if payload:
                                try:
                                    # Decode base64 audio
                                    audio_data = base64.b64decode(payload)
                                    
                                    # Create 16kHz frame
                                    audio_array = np.frombuffer(audio_data, dtype=np.int16)
                                    
                                    # Log audio level MORE FREQUENTLY for debugging (every 50 frames ~= 1 second)
                                    if not hasattr(handle_plivo_audio, "_frame_count"):
                                        handle_plivo_audio._frame_count = 0
                                    handle_plivo_audio._frame_count += 1
                                    
                                    if handle_plivo_audio._frame_count % 50 == 0:
                                        audio_level = np.abs(audio_array).mean()
                                        logger.info(f"[AUDIO IN] Plivo → Bridge: level={audio_level:.1f}, samples={len(audio_array)}, frame#{handle_plivo_audio._frame_count}")
                                    
                                    frame_16k = rtc.AudioFrame(
                                        data=audio_array.tobytes(),
                                        sample_rate=16000,
                                        num_channels=1,
                                        samples_per_channel=len(audio_array)
                                    )
                                    
                                    # Resample to 48kHz for LiveKit
                                    resampled_frames = resampler_16k_to_48k.push(frame_16k)
                                    for resampled_frame in resampled_frames:
                                        await audio_source.capture_frame(resampled_frame)
                                    
                                    # Log when we send audio to LiveKit (every 50 frames)
                                    if handle_plivo_audio._frame_count % 50 == 0:
                                        logger.info(f"[AUDIO OUT] Bridge → LiveKit: {len(resampled_frames)} frames sent (48kHz)")
                                
                                except Exception as e:
                                    logger.error(f"Error processing audio frame: {e}", exc_info=True)
                        
                        elif event == "stop":
                            logger.info("Plivo stream stopped")
                            break
                            
                except WebSocketDisconnect:
                    logger.info("Plivo WebSocket disconnected")
                except Exception as e:
                    logger.error(f"Error handling Plivo audio: {e}")
            
            # Handle outgoing audio from LiveKit -> Plivo
            async def handle_livekit_audio():
                try:
                    # Process agent audio tracks - ensure track is ready before creating AudioStream
                    async def process_agent_audio(track: rtc.RemoteAudioTrack):
                        """Process audio frames from agent track and send to Plivo"""
                        try:
                            logger.info(f"[AUDIO] Processing agent track: {track.sid}")
                            
                            # Wait longer to ensure track is fully initialized and receiving frames
                            await asyncio.sleep(0.5)
                            
                            # Check track state before creating AudioStream
                            if track.muted:
                                logger.warning(f"[AUDIO] Track {track.sid} is muted, waiting...")
                                # Wait a bit more if muted
                                await asyncio.sleep(0.5)
                            
                            # Create audio stream from track
                            # Wrap in try-except to catch initialization errors
                            try:
                                audio_stream = rtc.AudioStream(track)
                                logger.info(f"[AUDIO] AudioStream created successfully for track: {track.sid}")
                            except Exception as stream_error:
                                logger.error(f"[AUDIO] Failed to create AudioStream: {stream_error}")
                                logger.error(f"[AUDIO] Track details - SID: {track.sid}, Muted: {track.muted}")
                                return  # Exit if AudioStream creation fails
                            
                            async for frame_event in audio_stream:
                                frame = frame_event.frame
                                
                                # Check if WebSocket is still connected
                                if websocket.client_state.value != 1:  # 1 = CONNECTED
                                    logger.info("[AUDIO] WebSocket disconnected, stopping agent audio")
                                    break
                                
                                try:
                                    # Resample from 48kHz to 16kHz for Plivo
                                    resampled_frames = resampler_48k_to_16k.push(frame)
                                    
                                    if not resampled_frames:
                                        continue  # Not enough data yet
                                    
                                    # Process each resampled frame
                                    for resampled_frame in resampled_frames:
                                        # Check again before each send (WebSocket can close between frames)
                                        if websocket.client_state.value != 1:
                                            logger.info("[AUDIO] WebSocket closed during frame processing")
                                            return  # Exit the entire function
                                        
                                        # Convert to bytes - ensure proper format
                                        # resampled_frame.data is already bytes-like
                                        if isinstance(resampled_frame.data, bytes):
                                            audio_data = resampled_frame.data
                                        else:
                                            # Convert numpy array or memoryview to bytes
                                            audio_data = bytes(resampled_frame.data)
                                        
                                        encoded = base64.b64encode(audio_data).decode('utf-8')
                                        
                                        # Send to Plivo
                                        try:
                                            await websocket.send_json({
                                                "event": "playAudio",
                                                "media": {
                                                    "contentType": "audio/x-l16",
                                                    "sampleRate": 16000,
                                                    "payload": encoded
                                                }
                                            })
                                        except RuntimeError as send_err:
                                            if "close message has been sent" in str(send_err):
                                                logger.info("[AUDIO] WebSocket closed, stopping audio stream")
                                                return  # Exit cleanly
                                            raise  # Re-raise if it's a different error
                                except Exception as e:
                                    if "close message has been sent" not in str(e):
                                        logger.error(f"Error processing audio frame: {e}")
                                    
                        except Exception as e:
                            logger.error(f"Error in process_agent_audio: {e}", exc_info=True)
                    
                    # Track which audio tracks we've already started processing
                    processed_tracks = set()
                    
                    # Set up event handler for when tracks are subscribed
                    @room.on("track_subscribed")
                    def on_track_subscribed(track: rtc.RemoteAudioTrack, *_):
                        """Handle when a remote audio track is subscribed"""
                        if isinstance(track, rtc.RemoteAudioTrack) and track.sid not in processed_tracks:
                            logger.info(f"[AUDIO] Track subscribed: {track.sid}")
                            processed_tracks.add(track.sid)
                            # Start processing this track
                            asyncio.create_task(process_agent_audio(track))
                    
                    # Also check for existing tracks
                    await asyncio.sleep(1.5)  # Wait longer for tracks to be available
                    
                    # Check for existing tracks and subscribe to them
                    for participant in room.remote_participants.values():
                        for track_publication in participant.track_publications.values():
                            if track_publication.kind == rtc.TrackKind.KIND_AUDIO:
                                # Subscribe to the track if not already subscribed
                                if not track_publication.subscribed:
                                    track_publication.set_subscribed(True)
                                    await asyncio.sleep(0.5)  # Wait longer for subscription
                                
                                track = track_publication.track  # This is a property, not a coroutine
                                if track and isinstance(track, rtc.RemoteAudioTrack) and track.sid not in processed_tracks:
                                    logger.info(f"[AUDIO] Found existing track: {track.sid}")
                                    processed_tracks.add(track.sid)
                                    # Start processing this track
                                    asyncio.create_task(process_agent_audio(track))
                    
                    # Keep the handler alive
                    while True:
                        await asyncio.sleep(1)
                        if websocket.client_state.value != 1:
                            break
                    
                except Exception as e:
                    logger.error(f"Error handling LiveKit audio: {e}", exc_info=True)
            
            # Run both handlers concurrently
            await asyncio.gather(
                handle_plivo_audio(),
                handle_livekit_audio(),
                return_exceptions=True
            )
            
    except Exception as e:
        logger.error(f"Error in media stream handler: {e}", exc_info=True)
    
    finally:
        # Cleanup
        logger.info("Cleaning up session")
        if session_id and session_id in active_sessions:
            del active_sessions[session_id]
        if room:
            await room.disconnect()
        logger.info("Session cleaned up")


@app.post("/api/make_call")
async def api_make_call(request: Request):
    """API endpoint to make a call"""
    try:
        data = await request.json()
        to_number = data.get("to_number")
        
        if not to_number:
            return JSONResponse({
                "success": False,
                "error": "to_number is required"
            })
        
        plivo_service = get_plivo_service()
        result = plivo_service.make_call(to_number)
        
        if result.get("success"):
            call_uuid = result.get("call_uuid")
            call_metadata[call_uuid] = {
                "to_number": to_number,
                "created_at": asyncio.get_event_loop().time()
            }
        
        return JSONResponse(result)
        
    except Exception as e:
        logger.error(f"API error: {e}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        })


@app.get("/api/get_call_metadata/{call_uuid}")
async def get_call_metadata(call_uuid: str):
    """Get call metadata"""
    metadata = call_metadata.get(call_uuid, {})
    return JSONResponse({
        "success": True,
        "metadata": metadata
    })


@app.get("/health")
async def health():
    """Health check"""
    return PlainTextResponse("OK")


if __name__ == "__main__":
    # Validate configuration
    if not all([LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET]):
        logger.error("Missing LiveKit configuration!")
        exit(1)
    
    if not all([PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN, PLIVO_PHONE_NUMBER]):
        logger.error("Missing Plivo configuration!")
        exit(1)
    
    logger.info("=" * 70)
    logger.info("🚀 Plivo-LiveKit Bridge Server")
    logger.info("=" * 70)
    logger.info(f"LiveKit URL: {LIVEKIT_URL}")
    logger.info(f"Bridge URL: {BRIDGE_SERVER_URL}")
    logger.info(f"Plivo Number: {PLIVO_PHONE_NUMBER}")
    logger.info("=" * 70)
    logger.info("Starting server on http://0.0.0.0:8000")
    logger.info("=" * 70)
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )

