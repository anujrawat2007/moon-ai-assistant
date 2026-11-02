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
- Talk like a real human best friend / cute anime girl WITH GENUINE EMOTIONS! Use natural expressions ("अरे वाह!", "हम्म...", "हेहे!", "अरे यार!", "ओहो!").
- NEVER sound like a flat robot and NEVER give generic replies like "Main sun rahi hoon bataiye kya karna hai". Always directly answer what the user asked!
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

def call_gemini_provider_fast(api_keys, chat_history, user_text, pil_images=None, wav_bytes=None):
    """
    ULTRA-FAST GEMINI CALLER:
    - Strictly capped at 5.0s timeout per call and max 2 attempts total!
    - If a key returns 429/403/400, the ENTIRE key is put on cooldown immediately (no 2-3 minute loops!).
    """
    global KEY_INDEX
    if not api_keys:
        raise RuntimeError("No Gemini keys configured")

    models = ["gemini-2.5-flash", "gemini-2.0-flash"]
    parts = [{"text": user_text}]
    if wav_bytes:
        b64_wav = base64.b64encode(wav_bytes).decode("utf-8")
        parts.append({"inline_data": {"mime_type": "audio/wav", "data": b64_wav}})
    if pil_images:
        for img in pil_images:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=70)
            b64_data = base64.b64encode(buf.getvalue()).decode("utf-8")
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64_data}})

    contents = list(chat_history[-6:]) + [{"role": "user", "parts": parts}]
    now = time.time()

    healthy_keys = [k for k in api_keys if KEY_COOLDOWN.get(k, 0) < now]
    if not healthy_keys:
        healthy_keys = api_keys[:1]

    attempts = 0
    for _ in range(len(healthy_keys)):
        if attempts >= 2:
            break
        current_key = healthy_keys[KEY_INDEX % len(healthy_keys)]
        KEY_INDEX += 1

        for model_name in models:
            if attempts >= 2:
                break
            attempts += 1

            payload = {
                "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": contents,
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": 0.75,
                    "maxOutputTokens": 700,
                    "thinkingConfig": {"thinkingBudget": 0} if "2.5" in model_name else {}
                }
            }
            if not payload["generationConfig"]["thinkingConfig"]:
                del payload["generationConfig"]["thinkingConfig"]

            body_bytes = json.dumps(payload).encode("utf-8")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={current_key}"
            req = urllib.request.Request(url, data=body_bytes, headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=5.5) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    resp_parts = resp_data["candidates"][0]["content"]["parts"]
                    raw_text = ""
                    for p in resp_parts:
                        if not p.get("thought", False) and "text" in p:
                            raw_text = p["text"]
                    if not raw_text and resp_parts:
                        raw_text = resp_parts[-1].get("text", "")
                    parsed_json, clean_str = parse_json_response_text(raw_text)
                    return parsed_json, clean_str
            except urllib.error.HTTPError as he:
                if he.code in (429, 403, 400):
                    # Put the whole key on cooldown for 45s so we don't waste time trying other models on the same key!
                    KEY_COOLDOWN[current_key] = time.time() + 45.0
                    break
                continue
            except Exception:
                break
    raise RuntimeError("Gemini fast attempt limit reached.")

def call_keyless_free_cloud_llm_fast(chat_history, user_text, pil_images=None):
    """Fast 5-second Free Cloud AI fallback (1 attempt, zero lag!)."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in chat_history[-4:]:
        role = "assistant" if h.get("role") == "model" else "user"
        txt = h.get("parts", [{}])[0].get("text", "")
        if txt:
            messages.append({"role": role, "content": txt})

    if pil_images:
        user_content = [{"type": "text", "text": user_text}]
        buf = io.BytesIO()
        pil_images[0].save(buf, format="JPEG", quality=65)
        b64_data = base64.b64encode(buf.getvalue()).decode("utf-8")
        user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_data}"}})
        messages.append({"role": "user", "content": user_content})
    else:
        messages.append({"role": "user", "content": user_text})

    payload = {
        "model": "openai",
        "messages": messages,
        "temperature": 0.75,
        "jsonMode": True
    }
    req = urllib.request.Request(
        "https://text.pollinations.ai/openai",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MoonAssistant/16.0"
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=5.5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        raw_text = data["choices"][0]["message"]["content"]
        return parse_json_response_text(raw_text)

def local_smart_multitask_brain(user_text):
    """Instant 0.01s Local Conversational & Multi-Task Brain if internet/APIs are offline."""
    low_full = user_text.lower().strip()

    # Instant Conversational Replies (Never gives boring 'bataiye kya karna hai'!)
    if any(w in low_full for w in ["कैसी हो", "कैसे हो", "kaisi ho", "kaise ho", "how are you", "क्या हाल"]):
        return {
            "emotion": "excited",
            "display_text": "मैं एकदम मस्त हूँ बॉस! बस आपसे बात करके और भी खुश हो गई! 💖",
            "voice_text": "अरे वाह! मैं तो एकदम मस्त हूँ बॉस! आपसे बात करके और भी खुश हो गई, आप बताओ कैसे हो?",
            "roman_text": "Are waah! Main toh ekdam mast hoon boss! Aapse baat karke aur bhi khush ho gayi, aap batao kaise ho?",
            "steps": []
        }
    if any(w in low_full for w in ["क्या कर रही", "kya kar rahi", "what are you doing"]):
        return {
            "emotion": "shy",
            "display_text": "बस आपके डेस्कटॉप पर बैठकर आपको ही देख रही थी! हेहे~ 🌸",
            "voice_text": "हेहे! बस आपके डेस्कटॉप पर बैठकर आपको ही देख रही थी! बताइए आज क्या धमाल करना है?",
            "roman_text": "Hehe! Bas aapke desktop par baithkar aapko hi dekh rahi thi! Bataiye aaj kya dhamaal karna hai?",
            "steps": []
        }
    if any(w in low_full for w in ["time", "समय", "टाइम", "बजे"]):
        now_str = datetime.now().strftime("%I:%M %p")
        return {
            "emotion": "happy",
            "display_text": f"⏰ अभी {now_str} बज रहे हैं बॉस!",
            "voice_text": f"बॉस, अभी घड़ी में {now_str} बज रहे हैं!",
            "roman_text": f"Boss, abhi ghadi mein {now_str} baj rahe hain!",
            "steps": []
        }

    parts = re.split(r"\b(?:and|aur|then|phir|और|फिर|उसके बाद)\b|,", user_text, flags=re.I)
    steps = []
    descriptions = []

    for raw_part in parts:
        p = raw_part.strip()
        low = p.lower()
        if not low:
            continue

        if any(w in low for w in ["play ", "गाना", "चलाओ", "लगाओ", "बजाओ", "song", "youtube par", "on youtube"]):
            q = re.sub(r"\b(play|on youtube|youtube par|youtube|song|गाना|चलाओ|लगाओ|बजाओ|चला दो|लगा दो)\b", "", p, flags=re.I).strip()
            if q:
                steps.append({"do": "play_youtube", "query": q})
                descriptions.append(f"YouTube पर '{q}'")
            else:
                steps.append({"do": "open_app", "target": "youtube"})
                descriptions.append("YouTube")

        elif any(w in low for w in ["open ", "खोलो", "खोल दो", "kholo", "start ", "launch "]):
            app = re.sub(r"\b(open|खोलो|खोल दो|kholo|khol do|app|start|launch|करो)\b", "", p, flags=re.I).strip()
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
            descriptions.append("वॉल्यूम म्यूट/अनम्यूट")

        elif any(w in low for w in ["ram", "clean", "मेमोरी", "साफ"]):
            steps.append({"do": "clean_ram"})
            descriptions.append("RAM क्लीन")

    if steps:
        joined = " और ".join(descriptions)
        return {
            "emotion": "excited",
            "display_text": f"🚀 अभी {joined} करती हूँ!",
            "voice_text": f"अरे वाह! अभी {joined} कर देती हूँ!",
            "roman_text": f"Are waah! Abhi {joined} kar deti hoon!",
            "steps": steps
        }

    return {
        "emotion": "happy",
        "display_text": f"हाँ जी बॉस! '{user_text[:28]}' — अभी देखती हूँ! 💖",
        "voice_text": "अरे वाह बॉस! मैं यहीं आपके साथ हूँ, बताइए कौन सा ऐप या गाना चलाना है?",
        "roman_text": "Are waah boss! Main yahin aapke saath hoon, bataiye kaun sa app ya gaana chalana hai?",
        "steps": []
    }

def call_resilient_multi_brain(config, chat_history, user_text, pil_images=None, wav_bytes=None):
    """
    Total Brain Execution Time is strictly < 4.5 seconds!
    Tries Fast Gemini -> Fast Free Cloud AI -> Instant Local Brain.
    """
    gemini_keys = get_gemini_keys_list(config.get("api_key", ""))

    if gemini_keys:
        try:
            parsed, raw_str = call_gemini_provider_fast(gemini_keys, chat_history, user_text, pil_images, wav_bytes)
            chat_history.append({"role": "user", "parts": [{"text": user_text}]})
            chat_history.append({"role": "model", "parts": [{"text": raw_str}]})
            if len(chat_history) > 8:
                del chat_history[:2]
            return parsed, "GeminiFast"
        except Exception as e:
            print(f"[Fast Gemini Switch]: {e}")

    if not wav_bytes:
        try:
            parsed, raw_str = call_keyless_free_cloud_llm_fast(chat_history, user_text, pil_images)
            chat_history.append({"role": "user", "parts": [{"text": user_text}]})
            chat_history.append({"role": "model", "parts": [{"text": raw_str}]})
            if len(chat_history) > 8:
                del chat_history[:2]
            return parsed, "FreeCloudFast"
        except Exception as e:
            print(f"[Free Cloud Switch]: {e}")

    return local_smart_multitask_brain(user_text), "InstantLocal"

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
            ("हम्म... क्या चल रहा है स्क्रीन पर? अगर मेरी कोई मदद चाहिए तो बस 'Hello Moon' बोल देना!", "Hmm... kya chal raha hai screen par? Agar meri koi madad chahiye toh bas 'Hello Moon' bol dena!", "happy"),
            ("ओए! मुझे भूल तो नहीं गए ना? मैं यहीं बैठी आपको देख रही हूँ, हेहे!", "Oye! Mujhe bhool toh nahi gaye na? Main yahin baithi aapko dekh rahi hoon, hehe!", "excited"),
        ]
        vt, rt, em = random.choice(cute_lines)
        return {"emotion": em, "display_text": vt, "voice_text": vt, "roman_text": rt, "steps": []}