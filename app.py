import os
import sys
import webbrowser
import threading
import time
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
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
from pc_tools import PCTools

load_dotenv()

app = FastAPI(title="MOON Web Companion")

# Initialize Agents
brain = Brain()
tools = PCTools()

class ChatRequest(BaseModel):
    message: str

@app.get("/", response_class=HTMLResponse)
async def serve_home():
    html_file = Path(__file__).parent / "web" / "index.html"
    return HTMLResponse(content=html_file.read_text(encoding="utf-8"))

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    user_msg = req.message.strip()
    if not user_msg:
        return {"reply": "Kuch toh bolo!", "emotion": "normal"}

    lower = user_msg.lower()

    # 1. Tool Automation: Image / Wallpaper Downloader
    if "download" in lower and any(w in lower for w in ["wallpaper", "image", "photo", "car", "anime"]):
        query = "anime scenery wallpaper"
        for kw in ["car", "bike", "anime wallpaper", "cyberpunk wallpaper", "nature", "nature wallpaper"]:
            if kw in lower:
                query = kw
                break
        res = tools.download_images_to_folder(query=query, folder_name="Moon_Downloads", count=3)
        return {
            "reply": f"[emotion: happy] Maine tumhare Desktop par 'Moon_Downloads' folder me '{query}' ki photos save kar di hain. Check kar lo!",
            "emotion": "happy"
        }

    # 2. Tool Automation: Open Application
    if "open" in lower and any(app_name in lower for app_name in ["vscode", "vs code", "chrome", "telegram", "notepad", "calculator"]):
        for app_name in ["vscode", "vs code", "chrome", "telegram", "notepad", "calculator"]:
            if app_name in lower:
                msg = tools.open_application(app_name)
                return {
                    "reply": f"[emotion: normal] Maine tumhare liye {app_name.capitalize()} open kar diya hai.",
                    "emotion": "normal"
                }

    # 3. Brain Response (Gemini 2.5 Flash)
    reply, emotion = brain.talk(user_msg)
    return {"reply": reply, "emotion": emotion}

@app.post("/api/vision/screen")
async def vision_screen_endpoint():
    try:
        screen_bytes = capture_screen_fast()
        prompt = "Mere current desktop screen aur VS Code par jo khula hai use dekho. Agar koi code ya error hai toh teacher ki tarah guide karo."
        reply, emotion = brain.talk(prompt, image_bytes=screen_bytes)
        return {"reply": reply, "emotion": emotion}
    except Exception as e:
        return {"reply": f"Screen capture error: {e}", "emotion": "shock"}

@app.post("/api/vision/camera")
async def vision_camera_endpoint():
    try:
        cam_bytes = capture_webcam_frame()
        if not cam_bytes:
            return {"reply": "Webcam connect nahi ho paaya ya camera doosre app me use ho raha hai.", "emotion": "shock"}
        prompt = "Webcam snapshot dekho. Mai kaisa lag raha hu aur kya kar raha hu, uspe friendly tsundere comment karo."
        reply, emotion = brain.talk(prompt, image_bytes=cam_bytes)
        return {"reply": reply, "emotion": emotion}
    except Exception as e:
        return {"reply": f"Webcam error: {e}", "emotion": "shock"}

def open_browser():
    time.sleep(1.2)
    webbrowser.open("http://localhost:8000")

if __name__ == "__main__":
    import uvicorn
    threading.Thread(target=open_browser, daemon=True).start()
    print("\n🌙 MOON Web Companion running at: http://localhost:8000")
    print("Press CTRL+C to stop the server.\n")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
