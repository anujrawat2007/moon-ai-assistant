import os
import sys
import wave
import numpy as np
import sounddevice as sd
from groq import Groq
from dotenv import load_dotenv

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

load_dotenv()

class VoiceListener:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        if not self.api_key or self.api_key == "your_groq_api_key_here":
            self.client = None
            print("[Listener Notice] GROQ_API_KEY not configured.")
        else:
            self.client = Groq(api_key=self.api_key)

    def record_audio(self, duration: float = 4.5, sample_rate: int = 44100, output_wav: str = "data/temp_mic.wav") -> str:
        """
        Records audio from microphone with stereo-safe Realtek compatibility,
        applies auto-gain amplification if voice is quiet, and displays a volume meter.
        """
        os.makedirs(os.path.dirname(output_wav), exist_ok=True)
        print(f"\n🎤 [LISTENING NOW] Boliye... ({duration} seconds)")

        # Record with 2 channels for maximum compatibility with Realtek drivers
        try:
            raw_audio = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=2, dtype=np.float32)
            sd.wait()
            # Downmix stereo to mono
            audio_mono = raw_audio.mean(axis=1)
        except Exception as e:
            print(f"[Mic Notice] Stereo record fallback to 1 channel: {e}")
            raw_audio = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1, dtype=np.float32)
            sd.wait()
            audio_mono = raw_audio.flatten()

        # Check peak amplitude & volume level
        peak = np.max(np.abs(audio_mono))
        meter_len = int(min(peak * 50, 20))
        meter_bar = "█" * meter_len + "░" * (20 - meter_len)
        print(f"🔊 Mic Input Level: [{meter_bar}] (Peak: {peak:.3f})")

        if peak < 0.01:
            print("⚠️ [Warning] Audio level bahut low/silent tha. Check kijiye ki microphone Windows settings me mute toh nahi hai.")

        # Auto-gain normalize so whisper gets crisp, clear volume
        if peak > 0.001:
            audio_normalized = audio_mono / peak * 0.95
        else:
            audio_normalized = audio_mono

        # Convert float32 to int16 PCM
        audio_int16 = (audio_normalized * 32767).astype(np.int16)

        # Save to 16kHz WAV for Whisper (resample by decimation: 44100 -> ~14700 or save direct 44100)
        # Groq Whisper accepts standard 44.1kHz or 16kHz WAV seamlessly
        with wave.open(output_wav, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_int16.tobytes())

        print("⚡ [Processing with Groq Whisper...]")
        return output_wav

    def transcribe(self, wav_path: str) -> str:
        """Sends WAV audio to Groq Whisper cloud API for ultra-fast transcription."""
        if not self.client:
            return ""

        try:
            with open(wav_path, "rb") as audio_file:
                transcription = self.client.audio.transcriptions.create(
                    file=("speech.wav", audio_file.read()),
                    model="whisper-large-v3",
                    prompt="Lumina anime assistant, Hinglish, Hindi, English"
                )
            text = transcription.text.strip()
            return text
        except Exception as e:
            print(f"[Transcription Error] {e}")
            return ""

    def listen_and_transcribe(self, duration: float = 4.5) -> str:
        wav_path = os.path.join(os.path.dirname(__file__), "..", "data", "temp_mic.wav")
        self.record_audio(duration=duration, output_wav=wav_path)
        return self.transcribe(wav_path)

if __name__ == "__main__":
    listener = VoiceListener()
    print("Testing 3-second recording...")
    res = listener.listen_and_transcribe(duration=3.0)
    print(f"Transcribed Text: '{res}'")
