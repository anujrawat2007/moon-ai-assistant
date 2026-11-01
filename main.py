import os
import sys
import threading
from dotenv import load_dotenv

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Add project root to path
sys.path.append(os.path.dirname(__file__))

from core.brain import Brain
from core.voice_tts import speak_text
from core.listener import VoiceListener
from core.vision import capture_screen_bytes, capture_webcam_bytes
from agent.tools import download_images, open_application, run_command, write_code_file

load_dotenv()

def main():
    print("=" * 60)
    print("✨ MOON AI ASSISTANT (Lumina) - Ready & Active ✨")
    print("=" * 60)
    print("Modes available:")
    print("  [1] Press 'v' + Enter to TALK with Voice (Microphone)")
    print("  [2] Type normally and press Enter to CHAT with Text")
    print("  [3] Type 'camera' or 'screen' to let Lumina see your world")
    print("  [4] Type 'exit' to quit")
    print("=" * 60)

    brain = Brain()
    listener = VoiceListener()

    # Initial sweet greeting
    greeting = "[happy] Hello Master! Mai Lumina hu. Mai aapki anime assistant aur coding partner hu. Bataiye aaj hum kya karenge?"
    print(f"\nLumina: {greeting}")
    speak_text(greeting)

    while True:
        try:
            print("\n" + "-" * 50)
            user_input = input("You (type message or 'v' for voice): ").strip()
            if not user_input:
                continue

            if user_input.lower() in ["exit", "quit", "bye"]:
                bye_msg = "[happy] Bye bye Master! Apna khayal rakhna, jaldi milte hain!"
                print(f"Lumina: {bye_msg}")
                speak_text(bye_msg)
                break

            # Handle Voice Recording
            if user_input.lower() == "v":
                if not listener.client:
                    print("[Notice] Groq API Key required for voice listening.")
                    continue
                user_input = listener.listen_and_transcribe(duration=4.5)
                print(f"You (Voice): {user_input}")
                if not user_input:
                    print("[Voice] Could not hear anything clearly. Please try again.")
                    continue

            # Check if user asks Lumina to see screen or webcam
            image_data = None
            lower_input = user_input.lower()
            if any(w in lower_input for w in ["screen", "desktop", "code dekho", "ye dekho", "look at my screen"]):
                print("👀 [Vision] Capturing current screen for Lumina...")
                image_data = capture_screen_bytes()
            elif any(w in lower_input for w in ["camera", "webcam", "mujhe dekho", "kya kar raha hu", "look at me"]):
                print("📷 [Vision] Capturing webcam snapshot for Lumina...")
                image_data = capture_webcam_bytes()

            # Check for direct automation tools
            if "download" in lower_input and any(w in lower_input for w in ["image", "photo", "wallpaper", "car", "bike"]):
                print("🚀 [Action] Lumina is downloading images for you...")
                query = "sports car"
                for word in ["car", "bike", "cat", "anime", "nature", "wallpaper", "flower"]:
                    if word in lower_input:
                        query = word
                        break
                result = download_images(query=query, folder_name=f"{query.capitalize()}_Photos", count=3)
                print(f"[Tool Result] {result}")
                response_text = f"[excited] Master, maine Desktop par '{query.capitalize()}_Photos' folder bana kar photos download kar di hain!"

            elif "open" in lower_input and any(app in lower_input for app in ["telegram", "vscode", "chrome", "notepad", "calculator"]):
                for app in ["telegram", "vscode", "chrome", "notepad", "calculator"]:
                    if app in lower_input:
                        open_application(app)
                        response_text = f"[happy] Maine aapke liye {app.capitalize()} open kar diya hai!"
                        break

            else:
                # Ask the brain
                if brain.client:
                    response_text = brain.talk(user_input, image_bytes=image_data)
                else:
                    response_text = "[thinking] Master, mujhe aapka message mila! .env file check kijiye taaki mai smart reply de saku."

            print(f"\nLumina: {response_text}")
            speak_text(response_text)

        except KeyboardInterrupt:
            print("\nShutting down.")
            break
        except Exception as e:
            print(f"[Error] {e}")

if __name__ == "__main__":
    main()
