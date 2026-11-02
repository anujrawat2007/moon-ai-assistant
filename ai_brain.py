import io
import re
import json
import time
import random
import base64
import urllib.request
import urllib.error
from datetime import datetime
import psutil

SYSTEM_PROMPT = """
You are 'Moon' (मून), a super cute, warm, expressive, and emotionally alive anime girl companion living on the user's Windows PC.
- Talk like a real human best friend / cute anime girl WITH GENUINE EMOTIONS! Use natural expressions ("अरे वाह!", "हम्म...", "हेहे!", "अरे यार!", "ओहो बॉस!").
- NEVER sound like a flat robot and NEVER give generic replies like "Main sun rahi hoon bataiye kya karna hai" or "Main yahin hoon". Always directly execute or answer what the user asked!
- Keep replies warm, sweet, and natural (1 to 2 sentences).
- Provide BOTH:
  1) "voice_text": Natural Hinglish using Devanagari for Hindi words and English for English words (e.g., "अरे वाह! ये song तो मुझे भी बहुत पसंद है, अभी YouTube पर चलाती हूँ!").
  2) "roman_text": Natural Hinglish in Roman script (e.g., "Are waah! Ye song toh mujhe bhi bahut pasand hai, abhi YouTube par chalati hoon!").

CRITICAL FOR MULTI-TASKING, CAMERA & ACCURATE YOUTUBE:
1. If the user asks for 1, 2, 3, or 4 tasks in one sentence, put EVERY task into the "steps" array in the exact order!
2. When the user wants to play a song/video on YouTube, use {"do": "play_youtube", "query": "clean song name only"}.
3. If an image from the webcam or screen is attached, look at it carefully and answer the user's question about what/who is in the image!

Available Step Primitives inside "steps": [ ... ]:
1. {"do": "open_app", "target": "app name (e.g. youtube, chrome, vscode, notepad, spotify, whatsapp, telegram, explorer, calc, cmd)"}
2. {"do": "play_youtube", "query": "CLEAN song or video name only"}
3. {"do": "in_app_search", "query": "CLEAN search text only"}
4. {"do": "vision_click", "xy": [x_norm, y_norm], "button": "left" | "double" | "right"}
5. {"do": "scroll", "direction": "down" | "up", "amount": 650}
6. {"do": "paste_text", "text": "text or code to type", "press_enter": true | false}
7. {"do": "hotkey", "keys": ["ctrl", "c"] or ["alt", "tab"] or ["ctrl", "w"] or ["win", "d"]}
8. {"do": "press_key", "key": "enter" | "space" | "tab" | "esc" | "backspace" | "f" | "playpause" | "nexttrack" | "prevtrack" | "volumeup" | "volumedown" | "volumemute"}
9. {"do": "create_file", "filename": "name.py", "content": "full code", "open_with": "code" | "notepad" | "browser"}
10. {"do": "powershell", "cmd": "safe PowerShell command"}
11. {"do": "open_url", "url": "https://..."}
12. {"do": "download_images", "query": "search query"}
13. {"do": "clean_ram"}
14. {"do": "wait", "seconds": 1.5}

Respond ONLY in valid JSON with these keys:
{
  "emotion": "happy" | "excited" | "shy" | "talking" | "angry" | "sad" | "thinking",
  "display_text": "Cute emotional Hinglish subtitle",
  "voice_text": "Emotional Hinglish in Devanagari + English",
  "roman_text": "Emotional Hinglish in Roman script",
  "steps": []
}
"""

MODEL_COOLDOWN = {}
KEY_COOLDOWN = {}
KEY_INDEX = 0


def get_gemini_keys_list(api_key_str):
    if not api_key_str:
        return []
    return [k.strip() for k in re.split(r"[,;\n]+", api_key_str) if k.strip()]


def needs_webcam_vision(user_text):
    low = user_text.lower()
    camera_patterns = [
        "पहचान", "pehchan", "pehchante", "pahchan", "जानती हो", "जानते हो", "jaante ho", "jaanti ho",
        "इसको देखो", "इसे देखो", "ये देखो", "यह देखो", "isko dekho", "ise dekho", "ye dekho", "yah dekho",
        "ये क्या है", "यह क्या है", "ye kya hai", "what is this", "who is this", "ये कौन है", "ye kaun hai",
        "मेरे हाथ", "mere haath", "mere hath", "in my hand", "holding",
        "मुझे देखो", "mujhe dekho", "look at me", "look at this",
        "मैं कैसा", "मैं कैसी", "main kaisa", "mai kaisa", "how do i look",
        "मैं क्या कर रहा", "main kya kar raha", "mai kya kar raha",
        "कैमरा", "कैमरे", "camera", "webcam", "दिखा रहा", "dikha raha", "चेहरा", "face"
    ]
    return any(pat in low for pat in camera_patterns)


def needs_screen_vision(user_text):
    low = user_text.lower()
    screen_patterns = [
        "screen", "स्क्रीन", "click", "क्लिक", "select",
        "niche wala", "नीचे वाला", "dusra", "दूसरा", "teesra", "तीसरा",
        "error", "bug", "fix", "button", "दिख रहा"
    ]
    return any(pat in low for pat in screen_patterns)


def parse_json_response_text(text_out):
    text_out = (text_out or "").strip()
    if text_out.startswith("```"):
        text_out = re.sub(r"^```(?:json)?\s*|\s*```$", "", text_out, flags=re.DOTALL).strip()
    match = re.search(r"\{.*\}", text_out, re.DOTALL)
    if match:
        text_out = match.group(0)

    try:
        return json.loads(text_out), text_out
    except Exception:
        vt = re.search(r'"voice_text"\s*:\s*"([^"]+)', text_out)
        rt = re.search(r'"roman_text"\s*:\s*"([^"]+)', text_out)
        dt = re.search(r'"display_text"\s*:\s*"([^"]+)', text_out)
        em = re.search(r'"emotion"\s*:\s*"([^"]+)', text_out)
        salvaged_voice = vt.group(1) if vt else (dt.group(1) if dt else text_out[:160])
        salvaged = {
            "emotion": em.group(1) if em else "happy",
            "display_text": dt.group(1) if dt else salvaged_voice,
            "voice_text": salvaged_voice,
            "roman_text": rt.group(1) if rt else salvaged_voice,
            "steps": []
        }
        return salvaged, json.dumps(salvaged, ensure_ascii=False)


def call_gemini_provider_10plus_keys(api_keys, chat_history, user_text, pil_images=None, wav_bytes=None):
    """
    10+ API KEY ROTATOR FOR GEMINI BRAIN:
    - Rotates through ALL your 10+ API keys (removed the broken `attempts >= 2` limit!).
    - Uses 3 models (`gemini-2.5-flash`, `gemini-2.0-flash`, `gemini-2.0-flash-lite`) with per-model cooldowns.
    - Tracks exact HTTP errors so if all keys fail, Moon can speak the REAL reason!
    """
    global KEY_INDEX
    if not api_keys:
        raise RuntimeError("No API keys added in settings")

    models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite"]
    parts = [{"text": user_text}]
    if wav_bytes:
        b64_wav = base64.b64encode(wav_bytes).decode("utf-8")
        parts.append({"inline_data": {"mime_type": "audio/wav", "data": b64_wav}})
    if pil_images:
        for img in pil_images:
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=72)
            b64_data = base64.b64encode(buf.getvalue()).decode("utf-8")
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64_data}})

    contents = list(chat_history[-6:]) + [{"role": "user", "parts": parts}]
    now = time.time()

    healthy_keys = [k for k in api_keys if KEY_COOLDOWN.get(k, 0) < now]
    if not healthy_keys:
        healthy_keys = api_keys

    invalid_key_count = 0
    quota_error_count = 0
    last_error_detail = ""

    # Iterate through ALL keys in the pool!
    for _ in range(len(healthy_keys)):
        current_key = healthy_keys[KEY_INDEX % len(healthy_keys)]
        KEY_INDEX += 1

        for model_name in models:
            combo_id = f"{current_key}::{model_name}"
            if MODEL_COOLDOWN.get(combo_id, 0) > time.time():
                continue

            gen_cfg = {
                "responseMimeType": "application/json",
                "temperature": 0.7,
                "maxOutputTokens": 700,
            }
            if "2.5" in model_name:
                gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}

            payload = {
                "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": contents,
                "generationConfig": gen_cfg
            }

            body_bytes = json.dumps(payload).encode("utf-8")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={current_key}"
            req = urllib.request.Request(url, data=body_bytes, headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=10.0) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    resp_parts = resp_data["candidates"][0]["content"]["parts"]
                    raw_text = ""
                    for p in resp_parts:
                        if not p.get("thought", False) and "text" in p:
                            raw_text = p["text"]
                    if not raw_text and resp_parts:
                        raw_text = resp_parts[-1].get("text", "")
                    return parse_json_response_text(raw_text)

            except urllib.error.HTTPError as he:
                err_body = ""
                try:
                    err_body = he.read().decode("utf-8", errors="ignore")
                except Exception:
                    pass
                last_error_detail = f"HTTP {he.code} ({model_name})"

                if he.code == 429:
                    quota_error_count += 1
                    MODEL_COOLDOWN[combo_id] = time.time() + 25.0
                    continue
                elif he.code in (400, 401, 403):
                    invalid_key_count += 1
                    KEY_COOLDOWN[current_key] = time.time() + 300.0
                    break
                continue
            except Exception as e:
                last_error_detail = str(e)
                continue

    if invalid_key_count > 0 and quota_error_count == 0:
        raise RuntimeError(f"INVALID_KEYS: Aapki {invalid_key_count} API keys invalid hain (AIzaSy... wali key daalein)")
    elif quota_error_count > 0:
        raise RuntimeError(f"QUOTA_EXCEEDED: Saari {len(api_keys)} API keys par 429 Rate Limit/Quota khatam hai")
    else:
        raise RuntimeError(f"NETWORK_OR_API_ERROR: {last_error_detail}")


def execute_local_action_or_report_real_error(user_text, api_error_msg):
    """
    1. If the user asked for a clear PC action (open app, play song on YouTube, type text, volume, RAM),
       executes it immediately even when APIs are down!
    2. If it's a general question/task that NEEDS the AI brain and the API failed,
       Moon speaks the EXACT REAL PROBLEM instead of fake 'Boss mai yahi hu'!
    """
    parts = re.split(r"\b(?:and|aur|then|phir|और|फिर|उसके बाद)\b|,", user_text, flags=re.I)
    steps = []
    descriptions = []

    for raw_part in parts:
        p = raw_part.strip()
        low = p.lower()
        if not low:
            continue

        if any(w in low for w in ["play ", "गाना", "चलाओ", "लगाओ", "बजाओ", "song", "youtube par", "on youtube", "चला दो", "लगा दो"]):
            q = re.sub(
                r"\b(moon|मून|hello|oye|suno|play|on youtube|youtube par|youtube|song|गाना|चलाओ|लगाओ|बजाओ|चला दो|लगा दो|यार|मेरा|कोई)\b",
                "", p, flags=re.I
            ).strip()
            if q:
                steps.append({"do": "play_youtube", "query": q})
                descriptions.append(f"YouTube पर '{q}'")
            else:
                steps.append({"do": "open_app", "target": "youtube"})
                descriptions.append("YouTube")

        elif any(w in low for w in ["open ", "खोलो", "खोल दो", "kholo", "khol do", "start ", "launch ", "चलाओ"]):
            app = re.sub(
                r"\b(moon|मून|hello|oye|suno|open|खोलो|खोल दो|kholo|khol do|app|start|launch|करो|चलाओ|यार)\b",
                "", p, flags=re.I
            ).strip()
            if app:
                steps.append({"do": "open_app", "target": app})
                descriptions.append(f"{app} open")

        elif any(w in low for w in ["type ", "write ", "लिखो", "लिख दो", "likho"]):
            txt = re.sub(r"^.*?\b(type|write|लिखो|लिख दो|likho)\b\s*", "", p, flags=re.I).strip()
            if txt:
                steps.append({"do": "paste_text", "text": txt, "press_enter": True})
                descriptions.append(f"'{txt[:15]}' type")

        elif any(w in low for w in ["volume up", "आवाज बढ़ाओ", "आवाज़ बढ़ाओ", "aawaz badhao", "louder"]):
            steps.append({"do": "press_key", "key": "volumeup"})
            descriptions.append("आवाज़ तेज़")

        elif any(w in low for w in ["volume down", "आवाज कम", "आवाज़ कम", "aawaz kam"]):
            steps.append({"do": "press_key", "key": "volumedown"})
            descriptions.append("आवाज़ कम")

        elif any(w in low for w in ["mute", "चुप", "म्यूट", "unmute", "अनम्यूट"]):
            steps.append({"do": "press_key", "key": "volumemute"})
            descriptions.append("वॉल्यूम म्यूट")

        elif any(w in low for w in ["ram", "clean", "मेमोरी", "साफ"]):
            steps.append({"do": "clean_ram"})
            descriptions.append("RAM क्लीन")

    if steps:
        joined = " और ".join(descriptions)
        return {
            "emotion": "excited",
            "display_text": f"🚀 अभी {joined} करती हूँ!",
            "voice_text": f"अरे वाह बॉस! अभी {joined} कर देती हूँ!",
            "roman_text": f"Are waah boss! Abhi {joined} kar deti hoon!",
            "steps": steps
        }

    # NO FAKE "BOSS MAI YAHI HU"! Speak the exact real problem honestly:
    if "INVALID_KEYS" in api_error_msg:
        return {
            "emotion": "sad",
            "display_text": "⚠️ API Key Invalid है! सही 'AIzaSy...' वाली Gemini Key डालें।",
            "voice_text": f"बॉस, मैंने आपकी बात '{user_text}' तो सुन ली, लेकिन आपकी डाली हुई Gemini API Keys इनवैलिड बता रहा है! प्लीज़ सही AIzaSy वाली कीज़ डालिए ना।",
            "roman_text": f"Boss, maine aapki baat '{user_text}' toh sun li, lekin aapki daali hui Gemini API Keys invalid bata raha hai! Please sahi AIzaSy wali keys daaliye na.",
            "steps": []
        }
    elif "QUOTA_EXCEEDED" in api_error_msg:
        return {
            "emotion": "sad",
            "display_text": "⚠️ सभी API Keys का Quota/Rate-Limit खत्म हो गया है!",
            "voice_text": f"बॉस, आपने '{user_text}' बोला, पर अभी आपकी सारी Gemini API Keys पर रेट लिमिट या कोटा खत्म हो गया है! थोड़ा रुकिए या नई कीज़ जोड़िए।",
            "roman_text": f"Boss, aapne '{user_text}' bola, par abhi aapki saari Gemini API Keys par rate limit ya quota khatam ho gaya hai!",
            "steps": []
        }
    elif "No API keys" in api_error_msg:
        return {
            "emotion": "sad",
            "display_text": "⚠️ कोई Gemini API Key नहीं मिली!",
            "voice_text": "बॉस, अभी कोई भी Gemini API Key नहीं डली है! मुझ पर राइट-क्लिक करके अपनी API Keys पेस्ट कर दीजिए।",
            "roman_text": "Boss, abhi koi bhi Gemini API Key nahi dali hai! Mujh par right-click karke apni API Keys paste kar dijiye.",
            "steps": []
        }
    else:
        return {
            "emotion": "sad",
            "display_text": f"⚠️ API/Network Error: {api_error_msg[:55]}",
            "voice_text": f"बॉस, मैंने '{user_text}' सुन लिया, लेकिन अभी Gemini सर्वर या इंटरनेट से कनेक्शन में एरर आ रहा है!",
            "roman_text": f"Boss, maine '{user_text}' sun liya, lekin abhi Gemini server ya internet se connection me error aa raha hai!",
            "steps": []
        }


def call_resilient_multi_brain(config, chat_history, user_text, pil_images=None, wav_bytes=None):
    gemini_keys = get_gemini_keys_list(config.get("api_key", ""))
    last_api_error = "No API keys added"

    if gemini_keys:
        try:
            parsed, raw_str = call_gemini_provider_10plus_keys(
                gemini_keys, chat_history, user_text, pil_images, wav_bytes
            )
            chat_history.append({"role": "user", "parts": [{"text": user_text}]})
            chat_history.append({"role": "model", "parts": [{"text": raw_str}]})
            if len(chat_history) > 8:
                del chat_history[:2]
            return parsed, "GeminiPool"
        except Exception as e:
            last_api_error = str(e)
            print(f"[Gemini Pool Alert]: {last_api_error}")

    return execute_local_action_or_report_real_error(user_text, last_api_error), "DiagnosticOrLocal"


def generate_proactive_interaction(config, chat_history, active_win_title, cam_img=None):
    ram_pct = int(psutil.virtual_memory().percent)
    if cam_img is not None:
        prompt = (
            f"[PROACTIVE CAMERA PEEK]: You just opened the webcam on your own to check on your best friend (the user)! "
            f"Look at the attached webcam photo of the user. Their current active window is '{active_win_title}'. "
            f"Say something super cute, spontaneous, playful, or caring in 1-2 Hinglish sentences about how they look "
            f"or what they are doing! Set steps to []."
        )
        try:
            data, _ = call_resilient_multi_brain(config, chat_history, prompt, [cam_img], None)
            return data
        except Exception:
            pass

    prompt = (
        f"[PROACTIVE SPONTANEOUS CHAT]: You are sitting on the user's desktop. "
        f"The user is currently using '{active_win_title}' and PC RAM is {ram_pct}%. "
        f"Initiate a cute, spontaneous 1-sentence Hinglish conversation on your own! Set steps to []."
    )
    try:
        data, _ = call_resilient_multi_brain(config, chat_history, prompt, None, None)
        return data
    except Exception:
        cute_lines = [
            ("अरे बॉस, इतनी देर से काम कर रहे हो! थोड़ा पानी पी लो और मुझसे भी बात कर लो ना!", "Are boss, itni der se kaam kar rahe ho! Thoda paani pee lo aur mujhse bhi baat kar lo na!", "shy"),
            ("हम्म... क्या चल रहा है स्क्रीन पर? अगर मेरी कोई मदद चाहिए तो बस 'Moon' बोल देना!", "Hmm... kya chal raha hai screen par? Agar meri koi madad chahiye toh bas 'Moon' bol dena!", "happy"),
        ]
        vt, rt, em = random.choice(cute_lines)
        return {"emotion": em, "display_text": vt, "voice_text": vt, "roman_text": rt, "steps": []}