import os
import sys
import time
import subprocess
from dotenv import load_dotenv

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Add workspace directory to path
sys.path.append(os.path.dirname(__file__))

from brain import Brain
from vision import capture_screen_fast, capture_webcam_frame
from voice import VoiceManager
from pc_tools import PCTools

load_dotenv()

def main():
    print("=" * 68)
    print("🌙 MOON - AI DESKTOP COMPANION & AUTOMATION ASSISTANT 🌙")
    print("=" * 68)
    print("Features Activated:")
    print("  • Open-LLM-VTuber Transparent Floating Desktop Avatar")
    print("  • LivePortrait / THA3 Procedural Face Animation & Lip-Sync")
    print("  • browser-use & Open-Interface PC Automation Engine")
    print("  • Gemini 2.5 Flash Multimodal Brain & Groq Whisper STT")
    print("-" * 68)
    print("Controls:")
    print("  [1] Type 'v' + Enter: Speak into Microphone")
    print("  [2] Type any message directly to chat")
    print("  [3] Say/Type 'camera dekho' for webcam vision analysis")
    print("  [4] Say/Type 'vs code dekho' / 'code samjhao' for screen reading")
    print("  [5] Say/Type 'download wallpaper' for automated image download")
    print("  [6] Type 'exit' to quit")
    print("=" * 68)

    # 1. Launch Transparent Desktop Avatar (Open-LLM-VTuber style)
    avatar_script = os.path.join(os.path.dirname(__file__), "avatar_engine.py")
    avatar_proc = None
    try:
        print("[Avatar] Starting Moon transparent desktop overlay...")
        avatar_proc = subprocess.Popen([sys.executable, avatar_script], cwd=os.path.dirname(__file__))
        time.sleep(1.0)
    except Exception as e:
        print(f"[Avatar Notice] Could not auto-launch avatar: {e}")

    try:
        brain = Brain()
        voice_mgr = VoiceManager()
        tools = PCTools()

        # Initial Welcome Greeting
        welcome_text = "[emotion: normal] Hmm... toh tum aa hi gaye. Ummeed hai aaj time waste nahi karoge. Chalo, batao kya kaam hai?"
        print(f"\nMoon: {welcome_text}\n")
        voice_mgr.speak(welcome_text)

        while True:
            try:
                print("-" * 55)
                user_input = input("You (Enter message or 'v' for voice): ").strip()
                if not user_input:
                    continue

                if user_input.lower() in ["exit", "quit", "bye"]:
                    bye_text = "[emotion: normal] Ja rahe ho? Theek hai, jaao. Lekin jo code sikha hai use practice karna mat bhoolna."
                    print(f"\nMoon: {bye_text}")
                    voice_mgr.speak(bye_text)
                    break

                # Voice Recognition
                if user_input.lower() == "v":
                    user_input = voice_mgr.listen_and_transcribe(duration=4.5)
                    print(f"You (Voice): {user_input}")
                    if not user_input:
                        print("[Voice] Aawaz nahi aayi. Dobara boliye.")
                        continue

                lower_input = user_input.lower()
                image_data = None

                # 1. Vision: Screen & VS Code
                if any(w in lower_input for w in ["vs code", "code dekho", "screen dekho", "error dekho", "error samjhao"]):
                    print("💻 [Vision] Capturing VS Code / Desktop screen for Moon...")
                    image_data = capture_screen_fast()
                
                # 2. Vision: Camera & User
                elif any(w in lower_input for w in ["camera dekho", "mujhe dekho", "look at me", "webcam"]):
                    print("📷 [Vision] Capturing webcam snapshot for Moon...")
                    image_data = capture_webcam_frame()

                # 3. browser-use & Open-Interface Automation: Image/Wallpaper Crawler
                if "download" in lower_input and any(w in lower_input for w in ["wallpaper", "image", "photo", "car", "anime"]):
                    print("🚀 [Automating] Crawling web and downloading images...")
                    query = "anime scenery wallpaper"
                    for kw in ["car", "bike", "anime wallpaper", "cyberpunk wallpaper", "nature"]:
                        if kw in lower_input:
                            query = kw
                            break
                    tool_res = tools.download_images_to_folder(query=query, folder_name="Moon_Downloads", count=3)
                    print(f"[Tool Result] {tool_res}")
                    response_text = f"[emotion: happy] Maine tumhare Desktop par 'Moon_Downloads' folder me {query} save kar di hain. Ab khush?"

                # 4. Open-Interface: App Launching
                elif "open" in lower_input and any(app in lower_input for app in ["vscode", "vs code", "chrome", "telegram", "notepad", "calculator"]):
                    for app in ["vscode", "vs code", "chrome", "telegram", "notepad", "calculator"]:
                        if app in lower_input:
                            tools.open_application(app)
                            response_text = f"[emotion: normal] Maine {app.capitalize()} open kar diya hai."
                            break

                # 5. Multimodal Brain Inference (Gemini 2.5 Flash)
                else:
                    response_text, emotion = brain.talk(user_input, image_bytes=image_data)

                # Output dialogue & speak with live lip-sync
                print(f"\nMoon: {response_text}\n")
                voice_mgr.speak(response_text)

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"[Main Error] {e}")

    finally:
        if avatar_proc:
            avatar_proc.terminate()

if __name__ == "__main__":
    main()
