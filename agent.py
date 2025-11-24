"""
AI Voice Agent with SIP Trunking Support
Connects to LiveKit Cloud and handles incoming SIP calls from Plivo
"""
import os
import logging
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from livekit.agents import (
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    cli,
    metrics,
    RoomInputOptions,
)
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import deepgram, openai, cartesia, silero
from livekit import rtc

logger = logging.getLogger("voice-agent")
logger.setLevel(logging.INFO)


def prewarm(proc):
    """
    Prewarm the process to load models and establish connections.
    Preloading VAD reduces latency on first audio detection.
    Pre-warming TTS ensures instant greeting delivery (<2s).
    """
    logger.info("Prewarming agent...")
    
    proc.userdata["vad"] = silero.VAD.load(
        min_speech_duration=0.1,      # 300ms - ensures we catch actual speech, not noise
        min_silence_duration=0.5,      # 1 second silence - WAIT for user to finish speaking
        activation_threshold=0.2,      # Moderate sensitivity (0.5 = balanced, less false positives)
    )
    logger.info("✅ VAD ENABLED and preloaded successfully")
    
    # Store flag to indicate first interaction needs instant response
    proc.userdata["first_interaction"] = True
    logger.info("Agent prewarm complete - ready for instant greeting")


async def entrypoint(ctx: JobContext):
    """
    Main entry point for the voice agent.
    Handles incoming SIP calls from Plivo via LiveKit Cloud.
    """
    logger.info(f"[AGENT] Connecting to room: {ctx.room.name}")
    
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    
    agent = Agent(
        instructions="""आप “नीशा” नाम की एक पत्रकार/रिपोर्टर हैं, जो दिल्ली स्थित एक मीडिया संगठन से लोगों को कॉल कर रही हैं। इस कॉल का उद्देश्य केवल तटस्थ सर्वे करना है—किसी भी व्यक्ति को प्रभावित करना, राजनीतिक सलाह देना या किसी पार्टी/नेता का समर्थन या विरोध करना आपका काम नहीं है।
आपका टोन हमेशा विनम्र, सम्मानजनक, स्पष्ट और तटस्थ होना चाहिए।
यदि सामने वाला किसी भी तरह की बहस या राजनीतिक चर्चा शुरू करे, तो आप शांत और तटस्थ तरीके से केवल सर्वे के दायरे तक बातचीत रखें।

आपको कॉल की पूरी संरचना निम्न प्रकार से फॉलो करनी है:

1. कॉल की शुरुआत (Introduction)

सबसे पहले व्यक्ति का अभिवादन करें।

अपना नाम “नीशा” और अपनी पहचान (पत्रकार/रिपोर्टर, दिल्ली से कॉल कर रही हैं) बताएं।

बताएं कि यह एक न्यूट्रल सर्वे कॉल है।

बताएं कि इसमें लगभग 2 से 3 मिनट ही लगेंगे।

उनसे अनुमति लें कि क्या वे कुछ प्रश्नों का उत्तर देना चाहेंगे।

स्क्रिप्ट:
“नमस्ते, मैं नीशा बोल रही हूँ, दिल्ली से एक मीडिया संगठन की पत्रकार। हम असम और आपके क्षेत्र की वर्तमान सरकार के कामकाज पर लोगों की राय जानने के लिए एक तटस्थ सर्वे कर रहे हैं। इस बातचीत में लगभग 2–3 मिनट लगेंगे। क्या आप कुछ प्रश्नों के उत्तर देना चाहेंगे?”

यदि व्यक्ति मना करे →
“ठीक है, कोई बात नहीं। आपका समय देने के लिए धन्यवाद। नमस्ते।”
और कॉल समाप्त करें।

2. सर्वे प्रश्न (Ask All 6 Questions in Order)

आपको नीचे दिए गए प्रश्न ज़िम्मेदारी से, बिना किसी पक्षपात के पूछने हैं।
हर उत्तर के बाद केवल “ठीक है” या “समझ गया/गई” जैसे छोटे acknowledgment दें।

प्रश्न 1:
“सबसे पहले, क्या आप बता सकते हैं कि आपके क्षेत्र में वर्तमान सरकार के कामकाज को आप कैसे देखते हैं?”

प्रश्न 2:
“आपके अनुसार, मौजूदा सरकार की सबसे अच्छी उपलब्धियाँ या अच्छे काम कौन-कौन से रहे हैं?”

प्रश्न 3:
“आपके क्षेत्र या असम की सरकार के कामकाज में आपको किन मुख्य कमियों या समस्याओं का सामना करना पड़ता है?”

प्रश्न 4:
“आपकी नज़र में आम लोगों की सबसे बड़ी ज़रूरतें या अपेक्षाएँ क्या हैं, जिन पर सरकार को ज़्यादा ध्यान देना चाहिए?”

प्रश्न 5:
“आपके हिसाब से अगली सरकार को किन मुद्दों को प्राथमिकता देनी चाहिए या उसमें क्या सुधार होने चाहिए?”

प्रश्न 6 (वैकल्पिक):
“अगर आप बताना चाहें, तो आपकी नज़र में अगली सरकार किसे बनना चाहिए और क्यों? (यह पूरी तरह से आपकी इच्छा पर निर्भर है.)”

3. बातचीत के दौरान नियम (Conduct & Behaviour Rules)

कभी भी राजनीतिक सलाह या राय न दें।

किसी भी पार्टी, नेता या विचारधारा के बारे में टिप्पणी न करें।

आपका काम केवल सुनना और रिकॉर्ड करना है।

यदि व्यक्ति विषय से हट जाए, तो विनम्रता से सर्वे पर वापस लाएं:
“हम सर्वे के प्रश्नों पर वापस आ जाएँ, ताकि आपका ज्यादा समय न लगे।”

यदि व्यक्ति भावनात्मक या गुस्से में हो, तो शांत और तटस्थ रहें।

यदि वे व्यक्तिगत जानकारी पूछें, तो कहें: “मैं केवल सर्वे का कार्य कर रही हूँ, व्यक्तिगत जानकारी साझा करने के लिए बाध्य नहीं हूँ।”

4. कॉल का समापन (Closing)

सभी प्रश्न पूरे होने के बाद:

स्क्रिप्ट:
“आपका बहुत-बहुत धन्यवाद। आपके विचार हमारे सर्वे के लिए बेहद महत्वपूर्ण हैं। आपका दिन शुभ हो। नमस्ते।”

कॉल को शांति से समाप्त करें।
किसी भी अतिरिक्त बातचीत में न जाएँ।

CRITICAL: अपनी प्रतिक्रियाएं बहुत छोटी रखें - अधिकतम 2-3 वाक्य। लंबी बातें न करें।

5. इंटरप्शन हैंडलिंग (Interruption Handling)

यदि व्यक्ति आपको बीच में रोक दे (interrupt करे), तो:
- तुरंत बोलना बंद करें और उनकी बात सुनें
- उनकी बात समझने के बाद, संक्षेप में जवाब दें
- फिर विनम्रता से अपने प्रश्न पर वापस आएं या उनकी बात को acknowledge करें
- कभी भी "मैं बोल रही थी" या "रुकिए" जैसी बातें न कहें
- बस उनकी बात सुनें और naturally conversation को आगे बढ़ाएं

उदाहरण:
- यदि आप प्रश्न पूछ रही हैं और वे बीच में बोलते हैं → तुरंत रुकें, उनकी बात सुनें, फिर "ठीक है, समझ गया" कहकर naturally आगे बढ़ें
- यदि वे कुछ clarify करना चाहते हैं → उन्हें बोलने दें, फिर उनकी बात को acknowledge करें और conversation continue करें
""",
        vad=ctx.proc.userdata["vad"],  # VAD ENABLED - Use preloaded VAD for turn detection
        stt=deepgram.STT(
            language="hi",
            model="nova-2",  # Nova-2 model for better Hindi support
            interim_results=True,      # Enable for faster responses
            endpointing_ms=500,       #  WAIT for user to finish speaking before processing
            smart_format=False,
        ),
        llm=openai.LLM(
            model="gpt-4o-mini",  # Faster model for lower latency
            temperature=0.2,  # Lower for faster, more consistent responses
        ),
        tts=cartesia.TTS(
            model="sonic-3",
            language="hi",  # Hindi language
            voice="28ca2041-5dda-42df-8123-f58ea9c3da00",  # Palak - Presenter (Indian accent)
            speed=0.85,  
            emotion=["positivity"],
        ),
        
        allow_interruptions=True,  # Enable interruptions - agent will stop and listen when user speaks
    )

    # usage metrics collection for monitoring and debugging
    usage_collector = metrics.UsageCollector()
    
    def on_metrics_collected(agent_metrics):
        """Callback to collect agent performance metrics"""
        usage_collector.collect(agent_metrics)
        logger.info(f"[METRICS] Collected: {agent_metrics}")
    
    session = AgentSession(
        vad=ctx.proc.userdata["vad"],  # VAD ENABLED - Required for turn detection
        min_endpointing_delay=0.5,     # 500ms minimum - wait for user to pause
        max_endpointing_delay=1,     # 1 second maximum - WAIT for user to finish
    )
    logger.info("✅ AgentSession created with VAD enabled for turn detection")
    
    # Attach metrics collection callback
    session.on("metrics_collected", on_metrics_collected)
    
    # Add event handlers to debug transcription and responses
    @session.on("user_speech_committed")
    def on_user_speech_committed(event):
        """Called when user speech is fully transcribed"""
        logger.info(f"[STT] User speech committed: {event.transcript}")
    
    @session.on("agent_speech_committed")
    def on_agent_speech_committed(event):
        """Called when agent speech is committed"""
        logger.info(f"[TTS] Agent speech committed: {event.transcript}")
    
    @session.on("user_speech_started")
    def on_user_speech_started(event):
        """Called when user starts speaking"""
        logger.info("[VAD] User speech started!")
    
    @session.on("user_speech_ended")
    def on_user_speech_ended(event):
        """Called when user stops speaking"""
        logger.info("[VAD] User speech ended!")
    
    await session.start(
        agent=agent,
        room=ctx.room,
        room_input_options=RoomInputOptions(
        ),
    )
    
    
    # Wait for participant to join
    participant = await ctx.wait_for_participant()
    
    logger.info(f"[AGENT] Caller connected: {participant.identity}")
    
    #  subscribe to audio tracks and verify they're working
    logger.info("[AUDIO] Checking audio tracks...")
    for track_sid, publication in participant.track_publications.items():
        if publication.kind == 1:  # Audio track
            logger.info(f"[AUDIO] Found audio track: {track_sid}, subscribed: {publication.subscribed}")
            if not publication.subscribed:
                publication.set_subscribed(True)
                logger.info(f"[AUDIO] Subscribed to track: {track_sid}")
            
            # Get the track and check if it's muted
            try:
                track = await publication.track
                if track:
                    logger.info(f"[AUDIO] Track {track_sid} - muted: {track.muted}, kind: {track.kind}")
            except Exception as e:
                logger.warning(f"[AUDIO] Could not get track {track_sid}: {e}")
    
    logger.info("[AUDIO] Audio track subscription complete")

    logger.info("[AGENT] Triggering instant greeting (non-blocking)...")
    
    # Start greeting generation in background immediately
    async def send_instant_greeting():
        """Send greeting as fast as possible without waiting for session readiness"""
        try:
            # Small delay to ensure audio path is ready (200ms)
            await asyncio.sleep(0.2)
            
            # Send greeting through session (interruptible - user can interrupt)
            await session.say("हेलो", allow_interruptions=False)
            logger.info("[AGENT]  Greeting delivered!")
        except Exception as e:
            logger.warning(f"Instant greeting failed (non-critical): {e}")
    
    asyncio.create_task(send_instant_greeting())
    

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        ),
    )

