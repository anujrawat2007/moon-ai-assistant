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

# Add root directory to sys.path
sys.path.append(os.path.dirname(__file__))

from brain import Brain
from vision import capture_screen_fast, capture_webcam_frame
from voice_and_avatar import VoiceAndAvatarController
from pc_controller import PCController
from core.listener import VoiceListener

load_dotenv()

def main():
    print("=" * 65)
    print("👑 SUZUNE HORIKITA - AI DESKTOP ASSISTANT & PAIR PROGRAMMER 👑")
    print("=" * 65)
    print("Controls:")
    print("  • Type 'v' + Enter: Speak into your microphone")
    print("  • Type message directly to chat")
    print("  • Say/Type 'camera dekho' to let Suzune analyze you via webcam")
    print("  • Say/Type 'VS Code dekho' to let Suzune analyze your code/errors")
    print("  • Say/Type 'download wallpaper' to automate image download")
    print("  • Type 'exit' to quit")
    print("=" * 65)

    # 1. Launch Suzune Transparent Desktop Overlay in background
    overlay_script = os.path.join(os.path.dirname(__file__), "avatar", "suzune_overlay.py")
    overlay_proc = None
    try:
        print("[Avatar] Launching Suzune Horikita Transparent Desktop Overlay...")
        overlay_proc = subprocess.Popen([sys.executable, overlay_script], cwd=os.path.dirname(__file__))
        time.sleep(1.0)
    except Exception as e:
        print(f"[Avatar Notice] Could not auto-launch overlay: {e}")

    try:
        brain = Brain()
        voice_ctrl = VoiceAndAvatarController()
        pc_ctrl = PCController()
        listener = VoiceListener()

        # Initial Tsundere Greeting
        welcome_text = "[emotion: normal] Hmm... toh tum aa hi gaye. Ummeed hai aaj time waste nahi karoge. Chalo, batao kya kaam hai?"
        print(f"\nHorikita: {welcome_text}\n")
        voice_ctrl.speak(welcome_text)

        while True:
            try:
                print("-" * 55)
                user_input = input("You (Enter message or 'v' for voice): ").strip()
                if not user_input:
                    continue

                if user_input.lower() in ["exit", "quit", "bye"]:
                    bye_text = "[emotion: normal] Ja rahe ho? Theek hai, jaao. Lekin jo code sikha hai use practice karna mat bhoolna."
                    print(f"\nHorikita: {bye_text}")
                    voice_ctrl.speak(bye_text)
                    break

                # Handle Voice Input
                if user_input.lower() == "v":
                    if not listener.client:
                        print("[Voice Notice] GROQ_API_KEY required in .env for voice transcription.")
                        continue
                    user_input = listener.listen_and_transcribe(duration=4.5)
                    print(f"You (Voice): {user_input}")
                    if not user_input:
                        print("[Voice] Koi aawaz nahi aayi. Dobara try kijiye.")
                        continue

                lower_input = user_input.lower()
                image_data = None

                # 1. Vision Triggers
                if any(term in lower_input for term in ["vs code", "code dekho", "screen dekho", "error dekho", "error samjhao"]):
                    print("💻 [Vision] Capturing VS Code / Desktop screen...")
                    image_data = capture_screen_fast()
                elif any(term in lower_input for term in ["camera dekho", "mujhe dekho", "look at me", "webcam"]):
                    print("📷 [Vision] Capturing webcam snapshot...")
                    image_data = capture_webcam_frame()

                # 2. PC Automation Triggers
                if "download" in lower_input and any(w in lower_input for w in ["wallpaper", "image", "photo", "car", "anime"]):
                    print("⚡ [Automating] Downloading requested images to Desktop...")
                    query = "anime scenery wallpaper"
                    for keyword in ["car", "bike", "anime wallpaper", "coding wallpaper", "nature"]:
                        if keyword in lower_input:
                            query = keyword
                            break
                    tool_msg = pc_ctrl.download_wallpapers_or_images(query=query, folder_name="Suzune_Downloads", count=3)
                    print(f"[Tool] {tool_msg}")
                    response_text = f"[emotion: happy] Maine tumhare Desktop par 'Suzune_Downloads' folder me {query} save kar di hain. Ab khush?"

                elif "open" in lower_input and any(app in lower_input for app in ["vscode", "chrome", "telegram", "notepad", "calculator"]):
                    for app in ["vscode", "chrome", "telegram", "notepad", "calculator"]:
                        if app in lower_input:
                            pc_ctrl.open_application(app)
                            response_text = f"[emotion: normal] Maine {app.capitalize()} open kar diya hai."
                            break
                else:
                    # 3. Brain Multimodal Inference
                    response_text, emotion = brain.talk(user_input, image_bytes=image_data)

                # Display and Speak with real-time lip-sync to the avatar
                print(f"\nHorikita: {response_text}\n")
                voice_ctrl.speak(response_text)

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"[Main Error] {e}")

    finally:
        if overlay_proc:
            overlay_proc.terminate()

if __name__ == "__main__":
    main()
