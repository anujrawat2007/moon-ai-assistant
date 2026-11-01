import asyncio
import os
import re
import edge_tts
import sounddevice as sd
import soundfile as sf
from dotenv import load_dotenv

load_dotenv()

DEFAULT_VOICE = os.getenv("VOICE_NAME", "en-US-AnaNeural")
DEFAULT_PITCH = os.getenv("VOICE_PITCH", "+20Hz")
DEFAULT_RATE = os.getenv("VOICE_RATE", "+0%")

def clean_text_for_speech(text: str) -> tuple[str, str | None]:
    """
    Extracts emotion tag (e.g. [happy], [sad], [thinking]) and cleans text for speech.
    Returns: (cleaned_text, emotion)
    """
    emotion_match = re.search(r"\[(.*?)\]", text)
    emotion = emotion_match.group(1).lower() if emotion_match else None
    cleaned_text = re.sub(r"\[.*?\]", "", text).strip()
    return cleaned_text, emotion

async def generate_speech_async(text: str, output_path: str, voice: str = DEFAULT_VOICE, pitch: str = DEFAULT_PITCH, rate: str = DEFAULT_RATE):
    """Generates speech file using free Edge-TTS."""
    communicate = edge_tts.Communicate(text, voice, pitch=pitch, rate=rate)
    await communicate.save(output_path)

def play_audio_file(file_path: str):
    """Plays audio file directly to speakers using soundfile and sounddevice (Direct hardware playback)."""
    abs_path = os.path.abspath(file_path)
    try:
        data, fs = sf.read(abs_path)
        sd.play(data, fs)
        sd.wait()
    except Exception as e:
        print(f"[Audio Playback Error] {e}")

def speak_text(text: str, voice: str = DEFAULT_VOICE, pitch: str = DEFAULT_PITCH, rate: str = DEFAULT_RATE) -> str | None:
    """
    Speaks the given text out loud with sweet anime pitch and returns detected emotion.
    """
    cleaned_text, emotion = clean_text_for_speech(text)
    if not cleaned_text:
        return emotion

    temp_audio = os.path.join(os.path.dirname(__file__), "..", "data", "temp_speech.mp3")
    os.makedirs(os.path.dirname(temp_audio), exist_ok=True)

    # Generate speech
    asyncio.run(generate_speech_async(cleaned_text, temp_audio, voice, pitch, rate))

    # Play speech directly through speakers
    play_audio_file(temp_audio)

    return emotion

if __name__ == "__main__":
    print("Testing direct audio playback...")
    speak_text("[happy] Testing! Agar aapko meri awaz aa rahi hai toh bolna!")
