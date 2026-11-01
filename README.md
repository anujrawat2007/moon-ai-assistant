# ✨ Moon AI Assistant (Lumina) ✨

A lightweight, 100% free multimodal anime desktop AI companion & pair programmer tailored for low-end PCs.

---

## 🌟 Features Implemented:
1. **Sweet Anime Voice (TTS):** Powered by Edge Cloud TTS with high anime pitch tuning (`+20Hz`). Completely free, zero GPU required.
2. **Brain & Multimodal Vision:** Powered by Google Gemini 2.5 Flash Free API. Can understand conversation, analyze webcam pictures, and read your code/desktop screen.
3. **Voice Listening (STT):** Powered by Groq Whisper Cloud API (`whisper-large-v3`). Transcribes speech in ~0.3 seconds with 0% PC load.
4. **Desktop Automation (Tools):**
   - Automatically downloads images (e.g. cars, wallpapers) and saves them into a designated folder on your Desktop.
   - Can launch applications (Telegram, VS Code, Chrome, Notepad, Calc).
   - Can run terminal commands and write/edit code files.
5. **Anime Character Overlay:**
   - Lightweight (< 30MB RAM, 0% GPU) transparent floating anime widget.
   - Draggable anywhere across your screen.
   - Dynamic expressions based on emotion tags (`[happy]`, `[surprised]`, `[thinking]`).

---

## 🚀 How to Run:
- **Option 1:** Double-click [`run_assistant.bat`](file:///d:/moon%20ai%20assistant/run_assistant.bat)
- **Option 2 (Terminal):**
  ```powershell
  cd "d:\moon ai assistant"
  .\venv\Scripts\activate
  python main.py
  ```

---

## 💬 How to Interact:
- Press **`v`** + Enter: Speak into your microphone for 4.5 seconds.
- Or type any message directly into the console.
- Say or type **"screen dekho"** / **"code dekho"**: Lumina takes a snapshot of your screen and analyzes what you're working on.
- Say or type **"camera dekho"** / **"mujhe dekho"**: Lumina takes a snapshot from your webcam and talks about it.
- Say or type **"download car images"**: Lumina downloads car photos and puts them into a `Car_Photos` folder on your Desktop.
- Say or type **"open telegram"** / **"open vscode"**: Lumina launches the application.

