import asyncio
import os
import re
import math
import time
import socket
import json
import edge_tts
import sounddevice as sd
import soundfile as sf
import numpy as np
from dotenv import load_dotenv

load_dotenv()

DEFAULT_VOICE = os.getenv("VOICE_NAME", "hi-IN-SwaraNeural")
DEFAULT_PITCH = os.getenv("VOICE_PITCH", "+20Hz")
DEFAULT_RATE = os.getenv("VOICE_RATE", "+0%")

class VoiceAndAvatarController:
    """
    Handles Edge-TTS speech generation, audio playback with RMS amplitude extraction
    for real-time lip-sync, and hair/body bounce physics triggers via UDP IPC.
    """
    def __init__(self, voice: str = DEFAULT_VOICE, pitch: str = DEFAULT_PITCH, rate: str = DEFAULT_RATE, overlay_port: int = 9876):
        self.voice = voice
        self.pitch = pitch
        self.rate = rate
        self.overlay_port = overlay_port
        
        # UDP socket for real-time IPC with desktop avatar
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Live avatar state
        self.current_emotion = "normal"
        self.mouth_openness = 0.0
        self.is_speaking = False

    def send_avatar_state(self, mouth: float, emotion: str | None = None):
        """Sends non-blocking UDP state packet to Suzune avatar overlay."""
        try:
            payload = {"mouth": round(mouth, 2)}
            if emotion:
                payload["emotion"] = emotion
            data = json.dumps(payload).encode("utf-8")
            self.sock.sendto(data, ("127.0.0.1", self.overlay_port))
        except Exception:
            pass

    def parse_emotion(self, text: str) -> tuple[str, str]:
        """Extracts [emotion: ...] tag and returns clean speech text and emotion name."""
        match = re.search(r"\[emotion:\s*([a-zA-Z]+)\]", text, re.IGNORECASE)
        emotion = match.group(1).lower() if match else "normal"
        clean_text = re.sub(r"\[emotion:\s*[a-zA-Z]+\]", "", text).strip()
        return clean_text, emotion

    async def _synthesize_edge_tts(self, text: str, output_file: str):
        communicate = edge_tts.Communicate(text, self.voice, pitch=self.pitch, rate=self.rate)
        await communicate.save(output_file)

    def speak(self, text_with_emotion: str) -> str:
        """
        Synthesizes anime voice, plays audio, and calculates real-time lip-sync amplitude.
        Transmits mouth openness & emotion packets to avatar overlay at 25 Hz.
        """
        clean_text, emotion = self.parse_emotion(text_with_emotion)
        self.current_emotion = emotion
        
        # Update emotion on avatar immediately
        self.send_avatar_state(mouth=0.0, emotion=emotion)

        if not clean_text:
            return emotion

        temp_audio = os.path.join(os.path.dirname(__file__), "data", "temp_speech.mp3")
        os.makedirs(os.path.dirname(temp_audio), exist_ok=True)

        # 1. Synthesize Audio
        asyncio.run(self._synthesize_edge_tts(clean_text, temp_audio))

        # 2. Play with Real-time Lip-Sync Amplitude Tracking
        try:
            data, fs = sf.read(temp_audio)
            if data.ndim > 1:
                data = data.mean(axis=1)

            chunk_size = int(fs * 0.04) # 40ms audio chunks
            self.is_speaking = True

            stream = sd.OutputStream(samplerate=fs, channels=1, dtype=np.float32)
            stream.start()

            for i in range(0, len(data), chunk_size):
                chunk = data[i:i + chunk_size]
                if len(chunk) == 0:
                    break

                stream.write(chunk.astype(np.float32))

                # RMS Volume for Lip-Sync
                rms = np.sqrt(np.mean(chunk**2))
                openness = min(1.0, float(rms * 7.5))
                self.mouth_openness = openness

                # Stream to avatar window
                self.send_avatar_state(mouth=openness)

            stream.stop()
            stream.close()

        except Exception as e:
            print(f"[Playback Error] {e}")
        finally:
            self.is_speaking = False
            self.mouth_openness = 0.0
            self.send_avatar_state(mouth=0.0, emotion=self.current_emotion)

        return emotion

if __name__ == "__main__":
    controller = VoiceAndAvatarController()
    test_phrase = "[emotion: blush] Baka... aise achanak se mat dekho mujhe. Mai bas tumhari help kar rahi hu."
    print("Testing Voice & Avatar State Streaming...")
    controller.speak(test_phrase)
    print("Finished.")
