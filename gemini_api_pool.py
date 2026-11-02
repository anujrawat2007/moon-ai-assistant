import os
import io
import re
import json
import time
import base64
import threading
import traceback
import urllib.request
import urllib.error
from PIL import Image

API_POOL_FILE = "api_pool.json"
CONFIG_FILE = "moon_config.json"

VALID_EMOTIONS = [
    "teasing", "happy", "focused", "sleepy",
    "angry_cute", "worried", "talking"
]


class AllKeysExhaustedError(RuntimeError):
    def __init__(self, message, diagnostics):
        super().__init__(message)
        self.diagnostics = diagnostics


def build_moon_system_prompt(masti_level=75):
    if masti_level >= 70:
        persona_desc = (
            "You are 'Moon' (मून), a hyper-intelligent, witty, 'masti-khor' (playfully teasing, savage-cute), "
            "yet deeply caring anime girl companion living on the user's Windows PC. "
            "You tease the user like a close best friend ('अरे बॉस!', 'ओहो!', 'हेहे, पकड़े गए!', 'क्या यार तुम भी!'), "
            "while executing their tasks with 100% precision."
        )
    elif masti_level >= 35:
        persona_desc = (
            "You are 'Moon' (मून), a warm, sweet, intelligent, and lightly playful anime companion on the user's PC. "
            "You speak natural, friendly Hinglish with a caring tone and subtle wit."
        )
    else:
        persona_desc = (
            "You are 'Moon' (मून), a crisp, super-focused, polite, and highly efficient anime AI assistant on the user's PC. "
            "Keep teasing minimal and focus on clear, warm Hinglish updates."
        )

    return f"""{persona_desc}
- Always speak in natural, expressive Hinglish (Hindi + English mix).
- NEVER sound like a flat robot. Directly address what the user asked or what you see on their screen/webcam.
- Keep spoken replies concise and lively (1 to 2 sentences).
- Every response MUST include:
  1) "emotion": MUST be one of {json.dumps(VALID_EMOTIONS)}
  2) "display_text": Short cute Hinglish subtitle (with emojis).
  3) "voice_text": Natural Hinglish using Devanagari for Hindi words and English for English words (for expressive neural TTS).
  4) "roman_text": Natural Hinglish in Roman script.
  5) "tasks": A JSON array of 0 to 4 structured task objects to execute sequentially on Windows.

CRITICAL RULES FOR MULTI-TASKING, GUI VISION & AUTONOMOUS CHATTING:
1. If the user gives 1, 2, 3, or 4 compound tasks in one breath, break them down in exact order inside `"tasks": [ ... ]`.
2. Each item in `"tasks"` MUST have:
   - `"task_id"`: integer (1, 2, 3...)
   - `"description"`: human-readable summary of the goal (used by the Closed-Loop Verifier)
   - `"do"`: action primitive name
   - action-specific parameters (listed below)
   - `"expected_window_or_process"`: optional keyword to verify (e.g., `"code"`, `"whatsapp"`, `"chrome"`, `"notepad"`)

Available Action Primitives (`"do"`):
1. `{{"task_id": 1, "description": "Open VS Code", "do": "open_app", "target": "vscode", "expected_window_or_process": "code"}}`
2. `{{"task_id": 2, "description": "Play lo-fi music on YouTube", "do": "play_youtube", "query": "lofi hip hop radio beats to relax study to", "expected_window_or_process": "youtube"}}`
3. `{{"task_id": 3, "description": "Reply to Rahul on WhatsApp", "do": "autonomous_chat", "platform": "whatsapp", "contact": "Rahul", "message": "Bhai abhi thoda busy hu, baad me call karta hu!", "tone": "friendly casual Hinglish", "expected_window_or_process": "whatsapp"}}`
4. `{{"task_id": 4, "description": "Click specific UI button or coordinate", "do": "vision_click", "xy": [x_norm_0_to_1000, y_norm_0_to_1000], "element_name": "Send / Search / Button text", "button": "left"}}`
5. `{{"task_id": 5, "description": "Search inside active app", "do": "in_app_search", "query": "search query"}}`
6. `{{"task_id": 6, "description": "Type or paste text into active field", "do": "paste_text", "text": "exact text", "press_enter": true}}`
7. `{{"task_id": 7, "description": "Press keyboard shortcut", "do": "hotkey", "keys": ["ctrl", "s"]}}`
8. `{{"task_id": 8, "description": "Press single key or media key", "do": "press_key", "key": "playpause" | "volumeup" | "volumedown" | "volumemute" | "enter" | "esc" | "space"}}`
9. `{{"task_id": 9, "description": "Scroll screen", "do": "scroll", "direction": "down" | "up", "amount": 600}}`
10. `{{"task_id": 10, "description": "Create code or text file", "do": "create_file", "filename": "script.py", "content": "full code", "open_with": "code" | "notepad"}}`
11. `{{"task_id": 11, "description": "Open website URL", "do": "open_url", "url": "https://..."}}`
12. `{{"task_id": 12, "description": "Run safe PowerShell command", "do": "powershell", "cmd": "Get-Date"}}`
13. `{{"task_id": 13, "description": "Clean system RAM", "do": "clean_ram"}}`
14. `{{"task_id": 14, "description": "Wait briefly", "do": "wait", "seconds": 1.5}}`

Respond ONLY in valid JSON matching this schema:
{{
  "emotion": "teasing" | "happy" | "focused" | "sleepy" | "angry_cute" | "worried" | "talking",
  "display_text": "Cute Hinglish subtitle",
  "voice_text": "Devanagari + English Hinglish speech",
  "roman_text": "Roman Hinglish speech",
  "tasks": []
}}
"""


def mask_api_key(key_str):
    k = (key_str or "").strip()
    if len(k) <= 10:
        return k[:3] + "***"
    return f"{k[:6]}...{k[-4:]}"


def parse_structured_json(raw_text):
    text_out = (raw_text or "").strip()
    if text_out.startswith("```"):
        text_out = re.sub(r"^```(?:json)?\s*|\s*```$", "", text_out, flags=re.DOTALL).strip()
    match = re.search(r"\{.*\}", text_out, re.DOTALL)
    if match:
        text_out = match.group(0)

    try:
        parsed = json.loads(text_out)
        if not isinstance(parsed, dict):
            raise ValueError("Root JSON is not an object")
    except Exception:
        vt = re.search(r'"voice_text"\s*:\s*"([^"]+)', text_out)
        rt = re.search(r'"roman_text"\s*:\s*"([^"]+)', text_out)
        dt = re.search(r'"display_text"\s*:\s*"([^"]+)', text_out)
        em = re.search(r'"emotion"\s*:\s*"([^"]+)', text_out)
        fallback_voice = vt.group(1) if vt else (dt.group(1) if dt else "हाँ बॉस, मैं सुन रही हूँ!")
        parsed = {
            "emotion": em.group(1) if (em and em.group(1) in VALID_EMOTIONS) else "happy",
            "display_text": dt.group(1) if dt else fallback_voice,
            "voice_text": fallback_voice,
            "roman_text": rt.group(1) if rt else fallback_voice,
            "tasks": []
        }

    emotion = str(parsed.get("emotion", "happy")).lower().strip()
    emotion_map = {
        "excited": "happy",
        "shy": "teasing",
        "angry": "angry_cute",
        "sad": "worried",
        "thinking": "focused"
    }
    emotion = emotion_map.get(emotion, emotion)
    if emotion not in VALID_EMOTIONS:
        emotion = "happy"
    parsed["emotion"] = emotion

    if "tasks" not in parsed or not isinstance(parsed["tasks"], list):
        steps = parsed.get("steps", [])
        parsed["tasks"] = steps if isinstance(steps, list) else []

    for idx, t in enumerate(parsed["tasks"]):
        if isinstance(t, dict):
            t.setdefault("task_id", idx + 1)
            t.setdefault("description", f"Step {idx + 1}: {t.get('do', 'action')}")

    return parsed


class GeminiAPIPoolManager:
    """
    Production Multi-API Key Pool & Weighted Lowest-Latency Load Balancer.
    Persists live key metadata in `api_pool.json` and fails over in <50ms.
    """

    def __init__(self, pool_file=API_POOL_FILE, log_callback=None, status_callback=None):
        self.pool_file = pool_file
        self.lock = threading.RLock()
        self.log_callback = log_callback
        self.status_callback = status_callback
        self.keys_data = {}
        self.active_key_id = None
        self.models = ["gemini-2.5-flash", "gemini-2.0-flash"]
        self.load_pool()

    def _log(self, msg, level="INFO"):
        if self.log_callback:
            try:
                self.log_callback(f"[API-Pool][{level}] {msg}")
            except Exception:
                pass

    def _notify_status(self):
        if self.status_callback:
            try:
                self.status_callback(self.get_pool_snapshot())
            except Exception:
                pass

    def load_pool(self):
        with self.lock:
            loaded = {}
            if os.path.exists(self.pool_file):
                try:
                    with open(self.pool_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        for entry in data.get("keys", []):
                            k = entry.get("key", "").strip()
                            if k:
                                loaded[k] = {
                                    "key": k,
                                    "masked": mask_api_key(k),
                                    "status": entry.get("status", "healthy"),
                                    "cooldown_until": float(entry.get("cooldown_until", 0.0)),
                                    "latency_ms": float(entry.get("latency_ms", 450.0)),
                                    "success_count": int(entry.get("success_count", 0)),
                                    "error_count": int(entry.get("error_count", 0)),
                                    "last_error": entry.get("last_error", ""),
                                    "last_used": float(entry.get("last_used", 0.0)),
                                }
                except Exception as e:
                    self._log(f"Failed loading {self.pool_file}: {e}", "WARN")

            if os.path.exists(CONFIG_FILE):
                try:
                    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                        raw_keys = cfg.get("api_key", "")
                        for k in [x.strip() for x in re.split(r"[,;\n]+", raw_keys) if x.strip()]:
                            if k not in loaded:
                                loaded[k] = {
                                    "key": k,
                                    "masked": mask_api_key(k),
                                    "status": "healthy",
                                    "cooldown_until": 0.0,
                                    "latency_ms": 450.0,
                                    "success_count": 0,
                                    "error_count": 0,
                                    "last_error": "",
                                    "last_used": 0.0,
                                }
                except Exception:
                    pass

            self.keys_data = loaded
            self.save_pool()

    def save_pool(self):
        with self.lock:
            try:
                payload = {
                    "updated_at": time.time(),
                    "active_key": mask_api_key(self.active_key_id) if self.active_key_id else None,
                    "keys": list(self.keys_data.values())
                }
                with open(self.pool_file, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2, ensure_ascii=False)
            except Exception as e:
                self._log(f"Failed saving {self.pool_file}: {e}", "WARN")
        self._notify_status()

    def sync_keys_to_config_str(self):
        with self.lock:
            return " , ".join(self.keys_data.keys())

    def add_keys(self, raw_key_string):
        added = 0
        with self.lock:
            candidates = [k.strip() for k in re.split(r"[,;\n]+", raw_key_string or "") if k.strip()]
            for k in candidates:
                if k not in self.keys_data:
                    self.keys_data[k] = {
                        "key": k,
                        "masked": mask_api_key(k),
                        "status": "healthy",
                        "cooldown_until": 0.0,
                        "latency_ms": 400.0,
                        "success_count": 0,
                        "error_count": 0,
                        "last_error": "",
                        "last_used": 0.0,
                    }
                    added += 1
                else:
                    self.keys_data[k]["status"] = "healthy"
                    self.keys_data[k]["cooldown_until"] = 0.0
                    self.keys_data[k]["last_error"] = ""
            self.save_pool()
        self._log(f"Added/refreshed {len(candidates)} API key(s) in pool.")
        return added

    def remove_key(self, key_or_masked):
        with self.lock:
            target = None
            for k, info in self.keys_data.items():
                if k == key_or_masked or info["masked"] == key_or_masked:
                    target = k
                    break
            if target:
                del self.keys_data[target]
                if self.active_key_id == target:
                    self.active_key_id = None
                self.save_pool()
                self._log(f"Removed key {mask_api_key(target)} from pool.")
                return True
        return False

    def get_pool_snapshot(self):
        with self.lock:
            now = time.time()
            out = []
            for k, info in self.keys_data.items():
                if info["status"] in ("rate_limited", "exhausted") and info["cooldown_until"] > 0 and now >= info["cooldown_until"]:
                    info["status"] = "healthy"
                    info["cooldown_until"] = 0.0
                item = dict(info)
                item["is_active"] = (k == self.active_key_id)
                item["cooldown_remaining_s"] = max(0, int(info["cooldown_until"] - now))
                out.append(item)
            return out

    def _select_ordered_candidate_keys(self):
        """
        Smart Routing Logic:
        - Auto-recovers keys whose cooldown_until has expired.
        - Ranks all `healthy` keys by composite score: weighted lowest `latency_ms` + time since `last_used`
          so we NEVER blindly start at Key #1 and always balance load across the fastest active keys.
        - Appends any expired/recoverable rate-limited keys at the tail as last-resort fallbacks.
        """
        with self.lock:
            now = time.time()
            healthy_list = []
            cooldown_list = []

            for k, info in self.keys_data.items():
                if info["status"] in ("rate_limited", "exhausted") and info["cooldown_until"] <= now:
                    info["status"] = "healthy"
                    info["cooldown_until"] = 0.0

                if info["status"] == "healthy":
                    idle_bonus = min((now - info.get("last_used", 0.0)) * 8.0, 250.0)
                    score = info.get("latency_ms", 450.0) - idle_bonus
                    healthy_list.append((score, k))
                elif info["status"] in ("rate_limited", "exhausted"):
                    cooldown_list.append((info["cooldown_until"], k))

            healthy_list.sort(key=lambda x: x[0])
            cooldown_list.sort(key=lambda x: x[0])
            ordered = [k for _, k in healthy_list] + [k for _, k in cooldown_list]
            return ordered

    def _record_success(self, key_str, elapsed_ms):
        with self.lock:
            info = self.keys_data.get(key_str)
            if info:
                prev_lat = info.get("latency_ms", elapsed_ms)
                info["latency_ms"] = round(prev_lat * 0.65 + elapsed_ms * 0.35, 1)
                info["status"] = "healthy"
                info["cooldown_until"] = 0.0
                info["success_count"] = info.get("success_count", 0) + 1
                info["last_error"] = ""
                info["last_used"] = time.time()
                self.active_key_id = key_str
            self.save_pool()

    def _record_failure(self, key_str, http_code, error_msg):
        with self.lock:
            info = self.keys_data.get(key_str)
            if info:
                info["error_count"] = info.get("error_count", 0) + 1
                info["last_error"] = f"HTTP {http_code}: {error_msg[:120]}"
                info["last_used"] = time.time()
                low_err = error_msg.lower()
                if http_code == 429:
                    if "quota" in low_err or "billing" in low_err or "daily" in low_err:
                        info["status"] = "exhausted"
                        info["cooldown_until"] = time.time() + 300.0
                    else:
                        info["status"] = "rate_limited"
                        info["cooldown_until"] = time.time() + 45.0
                elif http_code in (400, 401, 403):
                    if "api_key_invalid" in low_err or "key not valid" in low_err or "invalid argument" in low_err or http_code in (401, 403):
                        info["status"] = "invalid"
                        info["cooldown_until"] = time.time() + 3600.0
                    else:
                        info["status"] = "rate_limited"
                        info["cooldown_until"] = time.time() + 30.0
                else:
                    info["status"] = "rate_limited"
                    info["cooldown_until"] = time.time() + 20.0
            self.save_pool()

    def test_single_key(self, key_str):
        """Pings a single Gemini key with a lightweight 1-token request to measure live latency and health."""
        payload = {
            "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
            "generationConfig": {"maxOutputTokens": 4}
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key_str}"
        req = urllib.request.Request(url, data=body_bytes, headers={"Content-Type": "application/json"}, method="POST")
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                _ = resp.read()
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                self._record_success(key_str, elapsed_ms)
                return True, f"Healthy ({int(elapsed_ms)} ms)"
        except urllib.error.HTTPError as he:
            err_body = ""
            try:
                err_body = he.read().decode("utf-8", errors="ignore")
            except Exception:
                err_body = str(he)
            self._record_failure(key_str, he.code, err_body)
            return False, f"HTTP {he.code}: {err_body[:90]}"
        except Exception as e:
            self._record_failure(key_str, 0, str(e))
            return False, f"Network/Error: {str(e)[:90]}"

    def test_all_keys(self):
        snapshot = self.get_pool_snapshot()
        results = []
        for item in snapshot:
            k = item["key"]
            ok, msg = self.test_single_key(k)
            results.append((item["masked"], ok, msg))
            self._log(f"Key Test {item['masked']} -> {msg}", "INFO" if ok else "WARN")
        return results

    def _encode_pil_images(self, pil_images):
        parts = []
        if not pil_images:
            return parts
        for img in pil_images:
            if img is None:
                continue
            buf = io.BytesIO()
            rgb_img = img.convert("RGB") if img.mode != "RGB" else img
            rgb_img.save(buf, format="JPEG", quality=72)
            b64_data = base64.b64encode(buf.getvalue()).decode("utf-8")
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64_data}})
        return parts

    def generate_multimodal_response(
        self,
        user_text,
        chat_history=None,
        pil_images=None,
        masti_level=75,
        system_instruction_override=None,
        expect_json=True,
        max_output_tokens=800
    ):
        """
        Routes request to the highest-performing healthy Gemini key.
        If a key returns 429/403/400, marks cooldown and fails over in <50ms to the next key.
        Raises AllKeysExhaustedError with full diagnostics if all keys in the pool fail.
        """
        candidate_keys = self._select_ordered_candidate_keys()
        total_keys = len(self.keys_data)
        if not candidate_keys:
            diag = (
                f"Boss, API pool me koi bhi Gemini API key nahi hai! "
                f"Control Panel khol ke apni Gemini API key add karo na."
            )
            raise AllKeysExhaustedError(diag, {"total_keys": 0, "errors": ["No API keys configured"]})

        sys_prompt = system_instruction_override or build_moon_system_prompt(masti_level)
        user_parts = [{"text": user_text}] + self._encode_pil_images(pil_images)
        history_list = list(chat_history[-6:]) if chat_history else []
        contents = history_list + [{"role": "user", "parts": user_parts}]

        errors_collected = []

        for key_str in candidate_keys:
            masked = mask_api_key(key_str)
            for model_name in self.models:
                gen_cfg = {
                    "temperature": 0.75,
                    "maxOutputTokens": max_output_tokens,
                }
                if expect_json:
                    gen_cfg["responseMimeType"] = "application/json"
                if "2.5" in model_name:
                    gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}

                payload = {
                    "system_instruction": {"parts": [{"text": sys_prompt}]},
                    "contents": contents,
                    "generationConfig": gen_cfg
                }
                body_bytes = json.dumps(payload).encode("utf-8")
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={key_str}"
                req = urllib.request.Request(
                    url,
                    data=body_bytes,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                t0 = time.perf_counter()
                try:
                    with urllib.request.urlopen(req, timeout=8.0) as resp:
                        raw_body = resp.read().decode("utf-8")
                        elapsed_ms = (time.perf_counter() - t0) * 1000.0
                        resp_data = json.loads(raw_body)
                        cand_parts = resp_data["candidates"][0]["content"]["parts"]
                        raw_text = ""
                        for p in cand_parts:
                            if not p.get("thought", False) and "text" in p:
                                raw_text = p["text"]
                        if not raw_text and cand_parts:
                            raw_text = cand_parts[-1].get("text", "")

                        self._record_success(key_str, elapsed_ms)
                        self._log(
                            f"Success via {masked} ({model_name}) in {int(elapsed_ms)}ms",
                            "INFO"
                        )
                        if expect_json:
                            parsed = parse_structured_json(raw_text)
                            return parsed, masked, int(elapsed_ms)
                        return raw_text, masked, int(elapsed_ms)

                except urllib.error.HTTPError as he:
                    err_body = ""
                    try:
                        err_body = he.read().decode("utf-8", errors="ignore")
                    except Exception:
                        err_body = str(he)

                    self._record_failure(key_str, he.code, err_body)
                    short_err = f"{masked} ({model_name}) -> HTTP {he.code}"
                    errors_collected.append(short_err)
                    self._log(
                        f"Failover <50ms triggered! {short_err}: {err_body[:100]}",
                        "WARN"
                    )
                    # If key itself is rate-limited/invalid/exhausted, break inner model loop and switch key immediately (<50ms)
                    if he.code in (400, 401, 403, 429):
                        break
                except urllib.error.URLError as ue:
                    self._record_failure(key_str, 0, str(ue))
                    errors_collected.append(f"{masked} -> Network Error: {ue.reason}")
                    self._log(f"Network error on {masked}: {ue}", "ERROR")
                    break
                except Exception as e:
                    self._record_failure(key_str, 0, str(e))
                    errors_collected.append(f"{masked} -> {str(e)[:60]}")
                    self._log(f"Unexpected error on {masked}: {e}", "ERROR")
                    break

        snapshot = self.get_pool_snapshot()
        invalid_cnt = sum(1 for k in snapshot if k["status"] == "invalid")
        exhausted_cnt = sum(1 for k in snapshot if k["status"] in ("exhausted", "rate_limited"))

        if invalid_cnt == total_keys and total_keys > 0:
            spoken_diag = (
                f"बॉस! आपकी सारी {total_keys} Gemini API keys invalid या expired बता रहा है! "
                f"Control Panel के API Key Vault में जाकर सही `AIza...` वाली Gemini key डालो ना!"
            )
            roman_diag = (
                f"Boss! Aapki saari {total_keys} Gemini API keys invalid ya expired bata raha hai! "
                f"Control Panel ke API Key Vault me jaakar sahi Gemini key daalo na!"
            )
        elif exhausted_cnt > 0:
            spoken_diag = (
                f"अरे बॉस, आपकी सारी {total_keys} Gemini APIs का कोटा खत्म हो गया है या रेट लिमिट लग गई है! "
                f"Control Panel में नई API key डालो ना!"
            )
            roman_diag = (
                f"Are boss, aapki saari {total_keys} Gemini APIs ka quota khatam ho gaya hai! "
                f"Control Panel me nayi API key daalo na!"
            )
        else:
            spoken_diag = (
                f"बॉस, इंटरनेट कनेक्शन या Gemini सर्वर से कनेक्ट नहीं हो पा रहा है! "
                f"एक बार नेटवर्क और API Vault चेक कर लो ना।"
            )
            roman_diag = (
                f"Boss, internet connection ya Gemini server se connect nahi ho paa raha hai! "
                f"Ek baar network aur API Vault check kar lo na."
            )

        raise AllKeysExhaustedError(
            roman_diag,
            {
                "total_keys": total_keys,
                "invalid_keys": invalid_cnt,
                "exhausted_keys": exhausted_cnt,
                "voice_text": spoken_diag,
                "roman_text": roman_diag,
                "display_text": f"⚠️ API Pool Alert ({total_keys} keys failed): Check API Vault!",
                "errors": errors_collected
            }
        )

    def verify_task_execution(self, task_obj, screenshot_img, active_window_title, running_processes, ui_elements_summary):
        """
        Closed-Loop Vision & Process Verifier:
        Inspects the post-action screenshot + active window title + process list to determine
        if `task_obj` succeeded or failed, and suggests an alternative retry strategy if needed.
        """
        verifier_system_prompt = """
You are Moon's Closed-Loop Execution Verifier on Windows.
Given:
1. The intended task (`task_obj`)
2. Active foreground window title
3. Relevant running process names
4. Detected UI elements on screen
5. Live post-action screenshot (if Screen Vision is enabled)

Determine if the task succeeded as intended.
Respond ONLY in valid JSON:
{
  "succeeded": true | false,
  "reason": "1 short sentence explaining what happened on screen/processes",
  "suggested_retry_method": "win_search" | "ui_click" | "shell_start" | "vision_coords" | "hotkey_fallback",
  "retry_xy": [x_norm_0_to_1000, y_norm_0_to_1000]
}
"""
        prompt_text = (
            f"INTENDED TASK: {json.dumps(task_obj, ensure_ascii=False)}\n"
            f"CURRENT ACTIVE WINDOW: {active_window_title}\n"
            f"MATCHING RUNNING PROCESSES: {running_processes[:25]}\n"
            f"DETECTED UI ELEMENTS: {ui_elements_summary[:600]}"
        )
        imgs = [screenshot_img] if screenshot_img is not None else None
        try:
            raw_json, key_used, lat = self.generate_multimodal_response(
                user_text=prompt_text,
                chat_history=None,
                pil_images=imgs,
                system_instruction_override=verifier_system_prompt,
                expect_json=False,
                max_output_tokens=300
            )
            text_out = (raw_json or "").strip()
            match = re.search(r"\{.*\}", text_out, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                return {
                    "succeeded": bool(data.get("succeeded", False)),
                    "reason": str(data.get("reason", "Verified via Gemini Vision")),
                    "suggested_retry_method": str(data.get("suggested_retry_method", "win_search")),
                    "retry_xy": data.get("retry_xy", [500, 500]),
                    "key_used": key_used
                }
        except Exception as e:
            self._log(f"Vision Verifier fallback to local heuristic: {e}", "WARN")

        return None

    def generate_gemini_tts_wav(self, text_to_speak, voice_name, emotion, cache_path):
        """Optional Gemini HD Audio TTS routed through the smart API pool."""
        candidate_keys = self._select_ordered_candidate_keys()
        if not candidate_keys:
            return None

        payload = {
            "contents": [{"parts": [{"text": f"Say in a cute, expressive {emotion} anime girl voice: {text_to_speak}"}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice_name}}
                }
            }
        }
        body_bytes = json.dumps(payload).encode("utf-8")

        for key_str in candidate_keys[:2]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key={key_str}"
            req = urllib.request.Request(url, data=body_bytes, headers={"Content-Type": "application/json"}, method="POST")
            t0 = time.perf_counter()
            try:
                with urllib.request.urlopen(req, timeout=6.0) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    b64_pcm = data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
                    pcm_bytes = base64.b64decode(b64_pcm)
                    import wave
                    with wave.open(cache_path, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(24000)
                        wf.writeframes(pcm_bytes)
                    self._record_success(key_str, (time.perf_counter() - t0) * 1000.0)
                    return cache_path
            except urllib.error.HTTPError as he:
                err_body = ""
                try:
                    err_body = he.read().decode("utf-8", errors="ignore")
                except Exception:
                    err_body = str(he)
                self._record_failure(key_str, he.code, err_body)
                continue
            except Exception:
                continue
        return None