import os
import sys
import time
import sounddevice as sd
import soundfile as sf
import numpy as np

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.append(os.path.dirname(__file__))

from core.voice_tts import speak_text
from core.listener import VoiceListener

def run_diagnostics():
    print("=" * 60)
    print("🔊 AUDIO & MIC DIAGNOSTIC TEST")
    print("=" * 60)

    # 1. Test Speaker Output
    print("\n[Step 1/2] Testing Speaker Output (Lumina ki awaz)...")
    test_phrase = "[happy] Namaste Master! Yeh mera audio test hai. Agar aapko meri awaz aa rahi hai toh speaker bilkul ready hai!"
    print("Speaking now...")
    speak_text(test_phrase)
    print("✅ Speaker test complete!")

    # 2. Test Microphone Input
    print("\n[Step 2/2] Testing Microphone Input...")
    print("Abhi aap mic me boliye: 'Hello Lumina testing'")
    time.sleep(1)

    listener = VoiceListener()
    transcription = listener.listen_and_transcribe(duration=4.0)
    
    print("\n" + "=" * 60)
    print("TEST RESULTS:")
    print(f"🎙️ Whisper Transcribed Text: '{transcription}'")
    if transcription:
        print("✅ Microphone aur Groq Whisper dono 100% kaam kar rahe hain!")
        speak_text("[excited] Master, maine aapki awaz bilkul saaf sun li hai!")
    else:
        print("⚠️ Mic se koi awaz detect nahi hui. Windows sound settings me check kijiye ki microphone muted toh nahi hai.")
    print("=" * 60)

if __name__ == "__main__":
    run_diagnostics()

