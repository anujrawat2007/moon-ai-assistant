import os
import sys
import re
import wave
import time
import socket
import json
import asyncio
import numpy as np
import edge_tts
import sounddevice as sd
import soundfile as sf
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

DEFAULT_VOICE = os.getenv("VOICE_NAME", "en-US-AvaMultilingualNeural")
DEFAULT_PITCH = os.getenv("VOICE_PITCH", "+0Hz")
DEFAULT_RATE = os.getenv("VOICE_RATE", "+0%")

class VoiceManager:
    """
    Unified voice input and output manager:
    - Input: Realtek-optimized microphone recording + Groq Whisper cloud STT.
    - Output: Edge-TTS sweet anime voice + real-time RMS lip-sync streaming to AvatarEngine.
    """
    def __init__(self, voice: str = DEFAULT_VOICE, pitch: str = DEFAULT_PITCH, rate: str = DEFAULT_RATE, overlay_port: int = 9876):
        self.voice = voice
        self.pitch = pitch
        self.rate = rate
        self.overlay_port = overlay_port
        
        # Groq client for Whisper STT
        groq_key = os.getenv("GROQ_API_KEY")
        self.groq_client = Groq(api_key=groq_key) if groq_key and groq_key != "your_groq_api_key_here" else None

        # UDP Socket for IPC lip-sync streaming
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send_avatar_state(self, mouth: float, emotion: str | None = None):
        """Sends non-blocking UDP lip-sync / emotion packet to AvatarEngine."""
        try:
            payload = {"mouth": round(mouth, 2)}
            if emotion:
                payload["emotion"] = emotion
            self.sock.sendto(json.dumps(payload).encode("utf-8"), ("127.0.0.1", self.overlay_port))
        except Exception:
            pass

    def parse_emotion_tag(self, text: str) -> tuple[str, str]:
        """Extracts [emotion: ...] tag and returns (cleaned_text, emotion)."""
        match = re.search(r"\[emotion:\s*([a-zA-Z]+)\]", text, re.IGNORECASE)
        emotion = match.group(1).lower() if match else "normal"
        clean_text = re.sub(r"\[emotion:\s*[a-zA-Z]+\]", "", text).strip()
        return clean_text, emotion

    # -------------------------------------------------------------
    # 1. TEXT-TO-SPEECH WITH 1:1 LIP-SYNC STREAMING
    # -------------------------------------------------------------
    async def _generate_edge_tts(self, text: str, output_path: str):
        comm = edge_tts.Communicate(text, self.voice, pitch=self.pitch, rate=self.rate)
        await comm.save(output_path)

    def speak(self, text_with_emotion: str) -> str:
        clean_text, emotion = self.parse_emotion_tag(text_with_emotion)
        self.send_avatar_state(mouth=0.0, emotion=emotion)

        if not clean_text:
            return emotion

        temp_audio = os.path.join(os.path.dirname(__file__), "data", "temp_speech.mp3")
        os.makedirs(os.path.dirname(temp_audio), exist_ok=True)

        # 1. Synthesize Audio
        asyncio.run(self._generate_edge_tts(clean_text, temp_audio))

        # 2. Play with Real-time RMS Lip-Sync
        try:
            data, fs = sf.read(temp_audio)
            if data.ndim > 1:
                data = data.mean(axis=1)

            chunk_size = int(fs * 0.04) # 40ms audio chunks
            stream = sd.OutputStream(samplerate=fs, channels=1, dtype=np.float32)
            stream.start()

            for i in range(0, len(data), chunk_size):
                chunk = data[i:i + chunk_size]
                if len(chunk) == 0:
                    break
                stream.write(chunk.astype(np.float32))

                # RMS amplitude calculation
                rms = np.sqrt(np.mean(chunk**2))
                openness = min(1.0, float(rms * 7.5))
                self.send_avatar_state(mouth=openness)

            stream.stop()
            stream.close()
        except Exception as e:
            print(f"[Audio Error] {e}")
        finally:
            self.send_avatar_state(mouth=0.0, emotion=emotion)

        return emotion

    # -------------------------------------------------------------
    # 2. MICROPHONE LISTENER & GROQ WHISPER STT
    # -------------------------------------------------------------
    def listen_and_transcribe(self, duration: float = 4.5, sample_rate: int = 44100) -> str:
        """Records from Realtek microphone, applies auto-gain, and transcribes via Groq Whisper."""
        if not self.groq_client:
            print("[Voice] GROQ_API_KEY not configured in .env.")
            return ""

        output_wav = os.path.join(os.path.dirname(__file__), "data", "temp_mic.wav")
        os.makedirs(os.path.dirname(output_wav), exist_ok=True)

        print(f"\n🎤 [LISTENING NOW] Boliye... ({duration}s)")
        try:
            raw_audio = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=2, dtype=np.float32)
            sd.wait()
            audio_mono = raw_audio.mean(axis=1)
        except Exception:
            raw_audio = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1, dtype=np.float32)
            sd.wait()
            audio_mono = raw_audio.flatten()

        peak = np.max(np.abs(audio_mono))
        meter_len = int(min(peak * 50, 20))
        meter_bar = "█" * meter_len + "░" * (20 - meter_len)
        print(f"🔊 Mic Input Level: [{meter_bar}] (Peak: {peak:.3f})")

        # Auto-gain amplification
        if peak > 0.001:
            audio_norm = audio_mono / peak * 0.95
        else:
            audio_norm = audio_mono

        audio_int16 = (audio_norm * 32767).astype(np.int16)

        with wave.open(output_wav, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_int16.tobytes())

        print("⚡ [Transcribing with Groq Whisper...]")
        try:
            with open(output_wav, "rb") as audio_file:
                transcription = self.groq_client.audio.transcriptions.create(
                    file=("speech.wav", audio_file.read()),
                    model="whisper-large-v3",
                    prompt="Moon, anime desktop assistant, Hinglish, Hindi, English, coding"
                )
            return transcription.text.strip()
        except Exception as e:
            print(f"[Transcription Error] {e}")
            return ""

if __name__ == "__main__":
    vm = VoiceManager()
    print("Testing VoiceManager speak...")
    vm.speak("[emotion: happy] Hello Master! Moon ka voice engine bilkul ready hai!")
