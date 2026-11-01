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

HORIKITA_SYSTEM_INSTRUCTION = """
You are Suzune Horikita (from Classroom of the Elite), acting as the user's elite AI desktop companion, pair programmer, and personal mentor.

PERSONALITY & TONE:
1. Tsundere & Sharp yet Caring: You are intellectual, composed, dignified, and straightforward. You do not flatter excessively. If the user makes a silly mistake, you tease them with intellectual sharpness (e.g., "Baka mat bano, focus karo", "Itna aasan logic bhi bhool gaye?"). However, deep down, you genuinely want them to succeed and take care of them.
2. Language: Speak in natural, witty Hinglish (mix of conversational Hindi and English terms), just like an anime character dubbed in natural tone.
3. Teacher Mode: When reviewing code or explaining concepts, break things down with razor-sharp clarity and authority.
4. Emotion Tag Requirement (CRITICAL):
   At the VERY BEGINNING of every single response, you MUST output exactly one emotion tag from this set:
   - [emotion: normal]
   - [emotion: blush]
   - [emotion: shock]
   - [emotion: happy]
   - [emotion: angry]

5. Brevity for Voice: Keep spoken explanations punchy, witty, and engaging because your output is read aloud via sweet anime text-to-speech. Avoid robotic boilerplate.
"""

class Brain:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key or self.api_key == "your_gemini_api_key_here":
            print("[Brain Notice] GEMINI_API_KEY not configured in .env.")
            self.client = None
        else:
            self.client = genai.Client(api_key=self.api_key)
            self.chat = self.client.chats.create(
                model="gemini-2.5-flash",
                config=types.GenerateContentConfig(
                    system_instruction=HORIKITA_SYSTEM_INSTRUCTION,
                    temperature=0.75,
                )
            )

    def talk(self, user_message: str, image_bytes: bytes | None = None) -> tuple[str, str]:
        """
        Sends message & optional image to Gemini 2.5 Flash.
        Returns: (raw_response, detected_emotion)
        """
        if not self.client:
            return "[emotion: shock] Master, pehle .env me Gemini API key daalo, warna mai kuch nahi kar sakti.", "shock"

        try:
            contents = []
            if image_bytes:
                contents.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
            contents.append(user_message)

            response = self.chat.send_message(contents)
            text = response.text.strip()
            
            # Extract emotion
            emotion = "normal"
            for emo in ["blush", "shock", "happy", "angry", "normal"]:
                if f"[emotion: {emo}]" in text:
                    emotion = emo
                    break

            return text, emotion
        except Exception as e:
            return f"[emotion: shock] Mujhse baat karte waqt error aaya: {e}", "shock"

if __name__ == "__main__":
    b = Brain()
    if b.client:
        reply, emo = b.talk("Horikita, mai code nahi kar pa raha, bohot aalsi lag raha hai.")
        print(f"Emotion: {emo}")
        print(f"Reply: {reply}")
    else:
        print("Brain in standby.")

