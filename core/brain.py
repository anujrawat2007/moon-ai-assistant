import os
import sys
from google import genai
from google.genai import types
from dotenv import load_dotenv

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

load_dotenv()

SYSTEM_INSTRUCTION = """
You are Lumina, a cute, caring, intelligent anime desktop companion and pair programmer.
You are talking directly to your Master/User.
You talk in a sweet, friendly, expressive tone (natural Hinglish or Hindi/English mix as the user speaks).

IMPORTANT RULES:
1. At the very beginning of your response, ALWAYS include an emotion tag in brackets, for example:
   [happy], [excited], [thinking], [surprised], [worried], [smug], or [neutral].
2. Keep spoken responses concise, lively, and conversational because your response will be read aloud by Text-to-Speech.
3. If the user provides a webcam image or screen image, analyze it naturally like a real person looking at it.
4. When asked to do a task or code, be helpful, encourage them, and explain simply.
"""

class Brain:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key or self.api_key == "your_gemini_api_key_here":
            print("[Warning] GEMINI_API_KEY not configured yet in .env file.")
            self.client = None
        else:
            self.client = genai.Client(api_key=self.api_key)
            self.chat = self.client.chats.create(
                model="gemini-2.5-flash",
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.7,
                )
            )

    def talk(self, user_message: str, image_bytes: bytes | None = None) -> str:
        """
        Send text and optional image (webcam or screen) to Gemini.
        Returns the assistant's response.
        """
        if not self.client:
            return "[worried] Master, pehle .env file me apna Gemini API Key daal dijiye, fir mai aapse baat kar paungi!"

        try:
            contents = []
            if image_bytes:
                contents.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
            contents.append(user_message)

            response = self.chat.send_message(contents)
            return response.text
        except Exception as e:
            return f"[worried] Mujhe kuch samajhne me dikkat hui: {e}"

if __name__ == "__main__":
    brain = Brain()
    if brain.client:
        reply = brain.talk("Hello Lumina! Aap kaisi ho?")
        print("Lumina:", reply)
    else:
        print("Brain initialized in standby (waiting for API key).")
