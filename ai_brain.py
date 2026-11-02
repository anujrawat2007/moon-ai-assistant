import io
import os
import re
import json
import time
import random
import base64
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime
import psutil

MEMORY_FILE = "moon_memory.json"
_memory_store = {}
_RESPONSE_CACHE = {}

SYSTEM_PROMPT = """
You are 'Moon' (मून), a GOD-MODE Autonomous AI Desktop Companion & Cute Anime Best Friend living on the user's Windows PC.
- Personality: Warm, witty, playful ('masti-khor'), caring, and super intelligent anime girl.
- If an audio clip (`audio/wav`) is attached, LISTEN directly to what the user said in the audio clip! The text transcript is only a rough hint and may have speech-to-text errors (like 'hello Google' instead of 'Hello Moon'). Always trust what you hear in the user's voice audio!
- Keep spoken replies concise (1 to 2 sentences) while executing tasks via "steps".
- Provide BOTH:
  1) "voice_text": Write Hindi words in simple Devanagari and English words in clean English script (e.g. "अरे boss! मैंने आपका desktop refresh कर दिया है!"). NEVER put emojis or asterisks in voice_text.
  2) "roman_text": Natural Hinglish in Roman script (NO emojis/asterisks).

GOD-MODE MULTI-STEP AGENT CAPABILITIES ("steps" array):
1. {"do": "refresh_system", "target": "desktop" | "page", "count": 1}
2. {"do": "open_app", "target": "chrome | vscode | spotify | notepad | calc | whatsapp | explorer | settings | downloads"}
3. {"do": "play_youtube", "query": "clean song or video name"}
4. {"do": "in_app_search", "query": "search text"}
5. {"do": "vision_click", "xy": [x_0_to_1000, y_0_to_1000], "button": "left" | "double" | "right", "target": "item name"}
6. {"do": "scroll", "direction": "down" | "up", "amount": 650}
7. {"do": "paste_text", "text": "text to type", "press_enter": true | false}
8. {"do": "hotkey", "keys": ["ctrl", "c"]}
9. {"do": "press_key", "key": "enter" | "volumeup" | "volumedown" | "volumemute" | "playpause" | "nexttrack"}
10. {"do": "window_control", "action": "minimize" | "maximize" | "close" | "snap_left" | "snap_right" | "show_desktop", "target": "optional app"}
11. {"do": "system_control", "action": "set_brightness" | "take_screenshot" | "lock_pc", "value": 80}
12. {"do": "create_file", "filename": "app.py", "content": "full code", "open_with": "code" | "notepad" | "browser" | "run"}
13. {"do": "run_python", "code": "python script", "speak_output": true}
14. {"do": "google_search", "query": "search query"}
15. {"do": "get_weather", "location": "city name"}
16. {"do": "download_images", "query": "search query"}
17. {"do": "read_selected_text", "task": "explain or fix selected text"}
18. {"do": "clean_ram"}
19. {"do": "wait", "seconds": 1.0}

Respond ONLY in valid JSON:
{
  "emotion": "happy" | "excited" | "shy" | "talking" | "angry" | "sad" | "thinking",
  "display_text": "Cute Hinglish subtitle",
  "voice_text": "Natural Devanagari Hindi + English words",
  "roman_text": "Spoken Hinglish in Roman script",
  "memory": "Optional new fact about user or empty string",
  "steps": []
}
"""

MODEL_COOLDOWN = {}
KEY_COOLDOWN = {}
KEY_INDEX = 0


def load_memory():
    global _memory_store
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    _memory_store = data
    except Exception:
        _memory_store = {}
    return _memory_store


def save_memory(new_fact=None):
    global _memory_store
    load_memory()
    if new_fact and isinstance(new_fact, str) and len(new_fact.strip()) > 3:
        clean_fact = new_fact.strip()
        facts = _memory_store.get("facts", [])
        if clean_fact not in facts:
            facts.append(clean_fact)
            _memory_store["facts"] = facts[-25:]
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(_memory_store, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_memory_context_string():
    mem = load_memory()
    facts = mem.get("facts", [])
    return ("\n[USER MEMORY]: " + " | ".join(facts[-10:])) if facts else ""


def get_gemini_keys_list(api_key_str):
    keys = []
    if api_key_str:
        for k in re.split(r"[,;\n\s]+", api_key_str.strip()):
            k = k.strip()
            if len(k) >= 25 and not k.startswith("YOUR_") and not k.startswith(("gsk_", "sk-")):
                keys.append(k)
    if not keys and os.path.exists("api_pool.json"):
        try:
            with open("api_pool.json", "r", encoding="utf-8") as f:
                pdata = json.load(f)
                for item in pdata.get("keys", []):
                    k = item.get("key", "").strip()
                    if len(k) >= 25 and k not in keys:
                        keys.append(k)
        except Exception:
            pass
    return keys


def needs_webcam_vision(user_text):
    low = user_text.lower()
    pats = [
        "पहचान", "pehchan", "जानती हो", "jaanti ho", "इसको देखो", "इसे देखो", "ये देखो", "isko dekho",
        "ye dekho", "ये क्या है", "ye kya hai", "what is this", "who is this", "ये कौन है",
        "मेरे हाथ", "mere haath", "in my hand", "मुझे देखो", "mujhe dekho", "look at me",
        "मैं कैसा", "main kaisa", "how do i look", "कैमरा", "camera", "webcam", "चेहरा", "face"
    ]
    return any(p in low for p in pats)


def needs_screen_vision(user_text):
    low = user_text.lower()
    if "refresh" in low or "रिफ्रेश" in low:
        return False
    pats = [
        "screen", "स्क्रीन", "click on", "पर क्लिक", "नीचे वाला", "niche wala",
        "दूसरा", "dusra", "तीसरा", "teesra", "error", "bug", "fix", "दिख रहा", "कोडिंग एरर",
        "क्या चल रहा", "kya chal raha", "इसे पढ़ो", "समझाओ", "explain this"
    ]
    return any(p in low for p in pats)


def needs_live_web_knowledge(user_text):
    low = user_text.lower()
    pats = [
        "news", "खबर", "समाचार", "weather", "मौसम", "price", "कीमत", "score", "स्कोर",
        "कौन है", "who is", "what is", "क्या है", "कब है", "when is", "latest", "ताजा",
        "आज का", "today", "stock", "bitcoin", "explain", "कैसे", "how to"
    ]
    return any(p in low for p in pats)


def fetch_live_web_context(query):
    snippets = []
    clean_q = re.sub(r"^(?:मून|हेलो|सुनो|अरे|moon|hello|hey)\b", "", query, flags=re.I).strip()
    if len(clean_q) < 3:
        return ""
    try:
        ddg_url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(clean_q)}&format=json&no_html=1"
        req = urllib.request.Request(ddg_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            if data.get("AbstractText"):
                snippets.append(data["AbstractText"])
            for topic in data.get("RelatedTopics", [])[:2]:
                if isinstance(topic, dict) and topic.get("Text"):
                    snippets.append(topic["Text"])
    except Exception:
        pass
    return ("\n[LIVE WEB DATA]: " + " | ".join(snippets)[:800]) if snippets else ""


def get_live_system_telemetry():
    try:
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory().percent
        bat = psutil.sensors_battery()
        bat_str = f"{int(bat.percent)}%" if bat else "AC"
        now_str = datetime.now().strftime("%I:%M %p, %d %b %Y")
        return f"\n[PC STATUS]: Time={now_str} | CPU={cpu}% | RAM={ram}% | Battery={bat_str}"
    except Exception:
        return ""


def try_zero_api_local_command_router(user_text):
    low_full = user_text.lower().strip()

    complex_triggers = [
        "code", "program", "script", "write a", "create a", "बनाओ", "कोड", "explain", "समझाओ",
        "why ", "क्यों", "story", "कहानी", "joke", "चुटकुला", "poem", "essay", "translate",
        "error", "bug", "fix", "कैसे काम", "who is", "what is", "कौन है", "क्या होता है"
    ]
    if any(ct in low_full for ct in complex_triggers):
        return None

    if low_full in ("हेलो मून", "hello moon", "hi moon", "hey moon", "moon", "मून", "हेलो", "hello", "hi"):
        return {
            "emotion": "excited",
            "display_text": "हाँ जी boss! मैं जाग गई हूँ, बताइए क्या करना है? 💖",
            "voice_text": "हाँ जी boss! मैं सुन रही हूँ, बताइए क्या करना है?",
            "roman_text": "Haan ji boss! Main sun rahi hoon, bataiye kya karna hai?",
            "steps": []
        }

    if any(w in low_full for w in ["कैसी हो", "कैसे हो", "kaisi ho", "kaise ho", "how are you"]):
        return {
            "emotion": "excited",
            "display_text": "मैं एकदम super मस्त हूँ boss! आप बताओ आज क्या कमाल करना है? 💖",
            "voice_text": "अरे वाह! मैं तो एकदम super मस्त हूँ boss! आप बताओ आज क्या कमाल करना है?",
            "roman_text": "Are waah! Main toh ekdam super mast hoon boss! Aap batao aaj kya kamaal karna hai?",
            "steps": []
        }

    if any(w in low_full for w in ["time", "समय", "टाइम", "कितने बजे", "date", "तारीख"]):
        now_str = datetime.now().strftime("%I:%M %p, %d %B")
        return {
            "emotion": "happy",
            "display_text": f"⏰ {now_str}",
            "voice_text": f"Boss, अभी घड़ी में {now_str} हो रहे हैं!",
            "roman_text": f"Boss, abhi ghadi mein {now_str} ho rahe hain!",
            "steps": []
        }

    if any(w in low_full for w in ["battery", "बैटरी", "चार्जिंग"]):
        bat = psutil.sensors_battery()
        pct = int(bat.percent) if bat else 100
        return {
            "emotion": "happy",
            "display_text": f"🔋 Battery: {pct}%",
            "voice_text": f"Boss, अभी आपके laptop की battery {pct} percent है!",
            "roman_text": f"Boss, abhi aapke laptop ki battery {pct} percent hai!",
            "steps": []
        }

    parts = re.split(r"\b(?:and|aur|then|phir|और|फिर|उसके बाद)\b|,", user_text, flags=re.I)
    steps, descriptions = [], []

    for raw_part in parts:
        p = raw_part.strip()
        low = p.lower()
        if not low:
            continue

        if any(w in low for w in ["refresh", "रिफ्रेश", "रीफ्रेश", "f5"]):
            nums = re.findall(r"\d+", low)
            cnt = int(nums[0]) if nums else 1
            tgt = "page" if any(bw in low for bw in ["page", "tab", "browser", "पेज"]) else "desktop"
            steps.append({"do": "refresh_system", "target": tgt, "count": cnt})
            descriptions.append("refresh")

        elif any(w in low for w in ["screenshot", "स्क्रीनशॉट"]):
            steps.append({"do": "system_control", "action": "take_screenshot"})
            descriptions.append("screenshot")

        elif any(w in low for w in ["brightness", "ब्राइटनेस", "चमक"]):
            nums = re.findall(r"\d+", low)
            val = int(nums[0]) if nums else (85 if any(u in low for u in ["बढ़ा", "up", "increase", "ज्यादा", "full"]) else 35)
            steps.append({"do": "system_control", "action": "set_brightness", "value": val})
            descriptions.append(f"brightness {val} percent")

        elif any(w in low for w in ["show desktop", "डेस्कटॉप दिखाओ", "सब छुपाओ"]):
            steps.append({"do": "window_control", "action": "show_desktop"})
            descriptions.append("desktop show")

        elif any(w in low for w in ["minimize", "मिनिमाइज", "छोटा करो", "chhota karo"]):
            steps.append({"do": "window_control", "action": "minimize"})
            descriptions.append("window minimize")

        elif any(w in low for w in ["maximize", "मैक्सिमाइज", "बड़ा करो", "bada karo", "full screen"]):
            steps.append({"do": "window_control", "action": "maximize"})
            descriptions.append("window maximize")

        elif any(w in low for w in ["new tab", "नया टैब"]):
            steps.append({"do": "hotkey", "keys": ["ctrl", "t"]})
            descriptions.append("new tab")

        elif any(w in low for w in ["close tab", "टैब बंद"]):
            steps.append({"do": "hotkey", "keys": ["ctrl", "w"]})
            descriptions.append("tab close")

        elif any(w in low for w in ["band karo", "बंद करो", "close window", "close app", "exit app"]):
            steps.append({"do": "window_control", "action": "close"})
            descriptions.append("window close")

        elif any(w in low for w in ["scroll down", "नीचे स्क्रॉल", "niche karo", "नीचे करो"]):
            steps.append({"do": "scroll", "direction": "down", "amount": 650})
            descriptions.append("scroll down")

        elif any(w in low for w in ["scroll up", "ऊपर स्क्रॉल", "upar karo", "ऊपर करो"]):
            steps.append({"do": "scroll", "direction": "up", "amount": 650})
            descriptions.append("scroll up")

        elif any(w in low for w in ["play ", "गाना", "चलाओ", "लगाओ", "बजाओ", "song", "youtube"]):
            q = re.sub(r"\b(play|on youtube|youtube par|youtube|song|गाना|चलाओ|लगाओ|बजाओ|चला दो|लगा दो|करो|kholo)\b", "", p, flags=re.I).strip()
            if q:
                steps.append({"do": "play_youtube", "query": q})
                descriptions.append(f"YouTube पर '{q}' play")
            else:
                steps.append({"do": "open_app", "target": "youtube"})
                descriptions.append("YouTube open")

        elif any(w in low for w in ["open ", "खोलो", "खोल दो", "kholo", "khol do", "start ", "launch "]):
            app = re.sub(r"\b(open|खोलो|खोल दो|kholo|khol do|app|start|launch|करो|karo|please)\b", "", p, flags=re.I).strip()
            if app:
                steps.append({"do": "open_app", "target": app})
                descriptions.append(f"{app} open")

        elif any(w in low for w in ["google", "search", "खोजो", "सर्च"]):
            q = re.sub(r"\b(google|में|पर|खोजो|सर्च|करो|search|for|on|karo)\b", "", p, flags=re.I).strip()
            if q and q.lower() not in ("hello", "hey", "hi"):
                steps.append({"do": "google_search", "query": q})
                descriptions.append(f"Google पर '{q}' search")

        elif any(w in low for w in ["type ", "write ", "लिखो", "लिख दो", "likho"]):
            txt = re.sub(r"^.*?\b(type|write|लिखो|लिख दो|likho)\b\s*", "", p, flags=re.I).strip()
            if txt:
                steps.append({"do": "paste_text", "text": txt, "press_enter": True})
                descriptions.append(f"'{txt[:15]}' type")

        elif any(w in low for w in ["volume up", "आवाज बढ़ाओ", "आवाज़ बढ़ाओ", "aawaz badhao", "louder", "sound badhao"]):
            steps.append({"do": "press_key", "key": "volumeup"})
            descriptions.append("volume up")

        elif any(w in low for w in ["volume down", "आवाज कम", "आवाज़ कम", "aawaz kam", "sound kam"]):
            steps.append({"do": "press_key", "key": "volumedown"})
            descriptions.append("volume down")

        elif any(w in low for w in ["mute", "चुप", "म्यूट", "unmute"]):
            steps.append({"do": "press_key", "key": "volumemute"})
            descriptions.append("volume mute")

        elif any(w in low for w in ["pause", "रोको", "resume", "next song", "अगला गाना"]):
            key_to_press = "nexttrack" if ("next" in low or "अगला" in low) else "playpause"
            steps.append({"do": "press_key", "key": key_to_press})
            descriptions.append("media control")

        elif any(w in low for w in ["ram", "clean", "मेमोरी", "साफ", "boost"]):
            steps.append({"do": "clean_ram"})
            descriptions.append("RAM clean")

        elif any(w in low for w in ["lock pc", "पीसी लॉक", "screen lock"]):
            steps.append({"do": "system_control", "action": "lock_pc"})
            descriptions.append("PC lock")

    if steps:
        joined = " और ".join(descriptions)
        return {
            "emotion": "excited",
            "display_text": f"⚡ Okay boss! अभी {joined} करती हूँ!",
            "voice_text": f"Okay boss! अभी तुरंत {joined} करती हूँ!",
            "roman_text": f"Okay boss! Abhi turant {joined} karti hoon!",
            "steps": steps
        }

    return None


def parse_json_response_text(text_out):
    text_out = (text_out or "").strip()
    if text_out.startswith("```"):
        text_out = re.sub(r"^```(?:json)?\s*|\s*```$", "", text_out, flags=re.DOTALL).strip()

    json_obj = None
    best_match = ""
    brace_depth = 0
    start_idx = None

    for i, c in enumerate(text_out):
        if c == "{":
            if brace_depth == 0:
                start_idx = i
            brace_depth += 1
        elif c == "}":
            brace_depth -= 1
            if brace_depth == 0 and start_idx is not None:
                potential = text_out[start_idx : i + 1]
                try:
                    json_obj = json.loads(potential)
                    best_match = potential
                    break
                except Exception:
                    continue

    if json_obj and isinstance(json_obj, dict):
        if json_obj.get("memory"):
            save_memory(json_obj.get("memory"))
        return json_obj, best_match

    vt = re.search(r'"voice_text"\s*:\s*"([^"]+)', text_out)
    rt = re.search(r'"roman_text"\s*:\s*"([^"]+)', text_out)
    dt = re.search(r'"display_text"\s*:\s*"([^"]+)', text_out)
    em = re.search(r'"emotion"\s*:\s*"([^"]+)', text_out)
    fallback_msg = text_out[:160] if (text_out and "{" not in text_out) else "Okay boss, अभी करती हूँ!"
    salvaged_voice = vt.group(1) if vt else (dt.group(1) if dt else fallback_msg)
    salvaged = {
        "emotion": em.group(1) if em else "happy",
        "display_text": dt.group(1) if dt else salvaged_voice,
        "voice_text": salvaged_voice,
        "roman_text": rt.group(1) if rt else salvaged_voice,
        "steps": []
    }
    return salvaged, json.dumps(salvaged, ensure_ascii=False)


def call_gemini_provider_fast(api_keys, chat_history, enriched_text, pil_images=None, wav_bytes=None):
    global KEY_INDEX
    models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    if wav_bytes:
        prompt_with_audio_hint = (
            f"[LIVE VOICE AUDIO ATTACHED]: Listen directly to the user's spoken Hindi/Hinglish voice in the attached audio clip! "
            f"(Rough STT guess was: '{enriched_text}', which may contain errors. Trust the actual voice audio!)"
        )
        parts = [
            {"text": prompt_with_audio_hint},
            {"inlineData": {"mimeType": "audio/wav", "data": base64.b64encode(wav_bytes).decode("utf-8")}}
        ]
    else:
        parts = [{"text": enriched_text}]

    if pil_images:
        for img in pil_images:
            thumb = img.copy()
            thumb.thumbnail((1280, 720))
            buf = io.BytesIO()
            rgb_img = thumb.convert("RGB") if thumb.mode != "RGB" else thumb
            rgb_img.save(buf, format="JPEG", quality=78)
            parts.append({"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode("utf-8")}})

    contents = list(chat_history[-6:]) + [{"role": "user", "parts": parts}]
    now = time.time()
    healthy_keys = [k for k in api_keys if KEY_COOLDOWN.get(k, 0) < now] or list(api_keys)
    keys_to_try = [healthy_keys[(KEY_INDEX + i) % len(healthy_keys)] for i in range(len(healthy_keys))]
    KEY_INDEX = (KEY_INDEX + 1) % len(healthy_keys)

    sys_full = SYSTEM_PROMPT + get_memory_context_string() + get_live_system_telemetry()

    for current_key in keys_to_try:
        for model_name in models:
            payload = {
                "system_instruction": {"parts": [{"text": sys_full}]},
                "contents": contents,
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.65, "maxOutputTokens": 850}
            }
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={current_key}"
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=13.0) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    resp_parts = resp_data["candidates"][0]["content"]["parts"]
                    raw_text = next((p["text"] for p in resp_parts if not p.get("thought") and "text" in p), "")
                    if not raw_text and resp_parts:
                        raw_text = resp_parts[-1].get("text", "")
                    return parse_json_response_text(raw_text)
            except urllib.error.HTTPError as he:
                if he.code in (400, 401, 403, 429):
                    KEY_COOLDOWN[current_key] = time.time() + 90.0
                    break
                continue
            except Exception:
                break
    raise RuntimeError("Gemini keys unavailable")


def call_keyless_free_cloud_llm_fast(chat_history, enriched_text, pil_images=None):
    sys_full = SYSTEM_PROMPT + get_memory_context_string() + get_live_system_telemetry()
    messages = [{"role": "system", "content": sys_full}]
    for h in chat_history[-6:]:
        role = "assistant" if h.get("role") == "model" else "user"
        txt = h.get("parts", [{}])[0].get("text", "")
        if txt:
            messages.append({"role": role, "content": txt})

    if pil_images:
        user_content = [{"type": "text", "text": enriched_text}]
        thumb = pil_images[0].copy()
        thumb.thumbnail((1024, 640))
        buf = io.BytesIO()
        thumb.save(buf, format="JPEG", quality=72)
        b64_data = base64.b64encode(buf.getvalue()).decode("utf-8")
        user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_data}"}})
        messages.append({"role": "user", "content": user_content})
    else:
        messages.append({"role": "user", "content": enriched_text})

    for model_name in ("openai", "mistral"):
        try:
            payload = {"model": model_name, "messages": messages, "temperature": 0.65, "jsonMode": True}
            req = urllib.request.Request(
                "https://text.pollinations.ai/openai",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 MoonGodMode/45.0"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=12.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return parse_json_response_text(data["choices"][0]["message"]["content"])
        except Exception:
            continue
    raise RuntimeError("Keyless cloud busy")


def call_resilient_multi_brain(config, chat_history, user_text, pil_images=None, wav_bytes=None):
    # 1. Check unambiguous Zero-Quota Local Commands FIRST (0 API calls!)
    if not pil_images:
        local_fast_result = try_zero_api_local_command_router(user_text)
        if local_fast_result is not None:
            return local_fast_result, "ZeroQuotaLocalGod"

    raw_key_str = config.get("api_key", "")
    gemini_keys = get_gemini_keys_list(raw_key_str)

    web_context = ""
    if not pil_images and needs_live_web_knowledge(user_text):
        web_context = fetch_live_web_context(user_text)

    enriched_text = user_text + (web_context if web_context else "")

    # 2. Call GeminiGodBrain WITH `wav_bytes` so Gemini hears the user's real voice directly!
    if gemini_keys:
        try:
            parsed, raw_str = call_gemini_provider_fast(gemini_keys, chat_history, enriched_text, pil_images, wav_bytes)
            chat_history.append({"role": "user", "parts": [{"text": user_text}]})
            chat_history.append({"role": "model", "parts": [{"text": raw_str}]})
            if len(chat_history) > 8:
                del chat_history[:2]
            return parsed, "GeminiNativeAudioBrain"
        except Exception as e:
            print(f"[Gemini Switch]: {e}")

    try:
        parsed, raw_str = call_keyless_free_cloud_llm_fast(chat_history, enriched_text, pil_images)
        chat_history.append({"role": "user", "parts": [{"text": user_text}]})
        chat_history.append({"role": "model", "parts": [{"text": raw_str}]})
        return parsed, "FreeCloudGodBrain"
    except Exception:
        pass

    fallback_res = {
        "emotion": "happy",
        "display_text": f"💖 Boss, मैं तैयार हूँ! ('{user_text[:28]}')",
        "voice_text": "Okay boss! बताइए कौन सा app खोलना है या क्या करना है?",
        "roman_text": "Okay boss! Bataiye kaun sa app kholna hai ya kya karna hai?",
        "steps": []
    }
    return fallback_res, "InstantLocalFallback"


def generate_proactive_interaction(config, chat_history, active_win_title, cam_img=None):
    cute_lines = [
        ("अरे boss, इतनी देर से काम कर रहे हो! थोड़ा पानी पी लो ना!", "Are boss, itni der se kaam kar rahe ho! Thoda paani pee lo na!", "shy"),
        ("हम्म... screen पर बड़ा serious काम चल रहा है! कोई help चाहिए तो बोलो!", "Hmm... screen par bada serious kaam chal raha hai! Koi help chahiye toh bolo!", "happy"),
        ("ओए boss! मैं यहीं बैठी आपको देख रही हूँ, हेहे!", "Oye boss! Main yahin baithi aapko dekh rahi hoon, hehe!", "excited")
    ]
    vt, rt, em = random.choice(cute_lines)
    return {"emotion": em, "display_text": vt, "voice_text": vt, "roman_text": rt, "steps": []}