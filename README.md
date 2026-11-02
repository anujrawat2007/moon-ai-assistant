# 🌙 Moon AI Assistant (Suzune Horikita Desktop Companion)

An intelligent, witty, and multimodal anime desktop companion & pair programmer for Windows PC.

---

## ✨ Features

- **🌸 Interactive Anime Sprite UI:**
  - Transparent, frameless, and draggable floating companion on your desktop.
  - Expressive anime expressions (`happy`, `teasing`, `focused`, `sleepy`, `angry_cute`, `worried`, `talking`, `hanging`).
  - Smooth breathing animation and real-time lip-syncing while speaking.

- **⚡ Multi-Key Gemini API Pool:**
  - Automatic load balancing with lowest-latency routing (< 50ms failover).
  - Exponential backoff and auto-cooldown on rate limits (429 / 503).
  - Zero downtime across multiple Google Gemini API keys.

- **🎙️ Dual Neural Voice & Audio Engine:**
  - Ultra-expressive Gemini Neural TTS & Microsoft Edge Neural TTS voices (Swara, Ana, Nanami, Zephyr, Aoede, Leda).
  - Pitch & rate customization, wake-word detection, and real-time audio formant RMS meter.

- **👁️ Multimodal Screen & Webcam Vision:**
  - Live desktop screen analysis (read error logs, inspect code, check open windows).
  - Webcam vision with privacy toggle and indicator.

- **🛡️ Closed-Loop OS Automation:**
  - Autonomous task planning and execution on Windows (open apps, in-app search, YouTube playback, typing/pasting, hotkeys, RAM cleanup).
  - Pre & post-execution verification to ensure requested actions succeed.

- **💡 Proactive Companion Daemon:**
  - Detects user inactivity and initiates caring or playful interactions when idle.

---

## 🚀 Getting Started

### 1. Prerequisites
- Windows 10/11
- Python 3.10+ installed and added to PATH

### 2. Installation
```powershell
# Clone the repository
git clone https://github.com/anujrawat2007/moon-ai-assistant.git
cd moon-ai-assistant

# Install required dependencies
pip install -r requirements.txt
```

### 3. Setup API Keys
1. Copy `moon_config.example.json` to `moon_config.json`:
   ```powershell
   copy moon_config.example.json moon_config.json
   ```
2. Open `moon_config.json` and paste your Gemini API key(s) separated by commas.

### 4. Run Moon
- **Option 1:** Double-click [`Start_Moon.bat`](file:///Start_Moon.bat)
- **Option 2 (Desktop Companion):**
  ```powershell
  python moon_assistant.py
  ```
- **Option 3 (Control Center UI):**
  ```powershell
  python main_ui.py
  ```

---

## 🎮 How to Interact
- **Click Moon:** Starts instant listening.
- **Double Click:** Toggle listening mode.
- **Right Click:** Opens the quick command center (settings, vision, RAM cleaner, voice selector).
- **Drag Moon:** Move her anywhere across your screen; place her at the bottom or top for special animations!

---

## 🔒 Privacy & Safety
- Your API keys are stored only locally in `moon_config.json` and are never committed or uploaded.
- Screen and webcam captures are only taken when triggered by you and processed securely.

