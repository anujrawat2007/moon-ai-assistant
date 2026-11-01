import os
import sys
import time
import math
import random
import socket
import json
import tkinter as tk
from PIL import Image, ImageTk

class AvatarEngine:
    """
    Combines the core concepts of Open-LLM-VTuber (transparent desktop overlay)
    and LivePortrait / THA3 (talking head procedural animation: head tilt, eye blinking,
    lip-sync, and hair physics bounce).
    
    Featherweight design: < 35MB RAM, 0% GPU load.
    """
    def __init__(self, target_height: int = 430, port: int = 9876):
        self.root = tk.Tk()
        self.root.title("Moon Avatar Engine")
        
        # Borderless, always-on-top transparent window (Open-LLM-VTuber style)
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)
        
        # Transparent chroma-key color
        self.bg_chroma = "#010203"
        self.root.wm_attributes("-transparentcolor", self.bg_chroma)
        self.root.config(bg=self.bg_chroma)

        # Asset management & scaling
        self.assets_dir = os.path.join(os.path.dirname(__file__), "avatar", "assets")
        self.orig_w, self.orig_h = 736, 900
        self.scale = target_height / float(self.orig_h)
        self.win_w = int(self.orig_w * self.scale)
        self.win_h = target_height

        # Position at bottom-right corner of desktop
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        pos_x = screen_w - self.win_w - 30
        pos_y = screen_h - self.win_h - 50
        self.root.geometry(f"{self.win_w}x{self.win_h}+{pos_x}+{pos_y}")

        # Drag-and-drop capability across desktop
        self._drag_data = {"x": 0, "y": 0}
        self.canvas = tk.Canvas(
            self.root, 
            width=self.win_w, 
            height=self.win_h, 
            bg=self.bg_chroma, 
            highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._do_drag)

        # Non-blocking UDP IPC socket for live lip-sync & emotion synchronization
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind(("127.0.0.1", port))
            self.sock.setblocking(False)
        except Exception as e:
            print(f"[AvatarEngine Notice] IPC Socket: {e}")

        # Live Animation & Physics State (THA3 / LivePortrait parameters)
        self.start_time = time.time()
        self.emotion = "normal"          # 'normal', 'blush', 'shock', 'angry', 'happy'
        self.mouth_openness = 0.0         # 0.0 (closed) to 1.0 (open)
        self.head_tilt_angle = 0.0        # Head pose parameter
        self.is_blinking = False
        self.next_blink_time = time.time() + random.uniform(2.5, 4.5)
        self.blink_end_time = 0.0

        # Hair & Braid Spring Physics (Hooke's Law: F = -k*x - c*v)
        self.braid_angle = 0.0
        self.braid_vel = 0.0
        self.braid_stiffness = 18.0
        self.braid_damping = 0.85

        # Pre-load sprites
        self._load_sprites()

        # Start 30 FPS Render Loop
        self.last_frame_time = time.time()
        self._render_loop()

    def _start_drag(self, event):
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def _do_drag(self, event):
        dx = event.x - self._drag_data["x"]
        dy = event.y - self._drag_data["y"]
        new_x = self.root.winfo_x() + dx
        new_y = self.root.winfo_y() + dy
        self.root.geometry(f"+{new_x}+{new_y}")

    def _load_sprites(self):
        """Pre-loads and scales base portrait and facial deformation overlays."""
        base_raw = Image.open(os.path.join(self.assets_dir, "horikita_transparent.png"))
        self.img_base = ImageTk.PhotoImage(base_raw.resize((self.win_w, self.win_h), Image.Resampling.LANCZOS))

        # Eyes Box: (215, 270, 520, 360)
        self.eyes_x = int(215 * self.scale)
        self.eyes_y = int(270 * self.scale)
        self.eyes_w = int((520 - 215) * self.scale)
        self.eyes_h = int((360 - 270) * self.scale)

        eyes_closed_raw = Image.open(os.path.join(self.assets_dir, "eyes_closed.png"))
        self.img_eyes_closed = ImageTk.PhotoImage(eyes_closed_raw.resize((self.eyes_w, self.eyes_h), Image.Resampling.LANCZOS))

        # Mouth Box: (340, 415, 400, 455)
        self.mouth_x = int(340 * self.scale)
        self.mouth_y = int(415 * self.scale)
        self.mouth_w = int((400 - 340) * self.scale)
        self.mouth_h = int((455 - 415) * self.scale)

        mouth_open_raw = Image.open(os.path.join(self.assets_dir, "mouth_open.png"))
        self.img_mouth_open = ImageTk.PhotoImage(mouth_open_raw.resize((self.mouth_w, self.mouth_h), Image.Resampling.LANCZOS))

        # Hair Braid Box: (490, 275, 736, 850)
        self.braid_anchor_x = int(490 * self.scale)
        self.braid_anchor_y = int(275 * self.scale)
        self.braid_w = int((736 - 490) * self.scale)
        self.braid_h = int((850 - 275) * self.scale)
        self.braid_raw = Image.open(os.path.join(self.assets_dir, "hair_braid.png"))

        # Emotion Overlays
        blush_raw = Image.open(os.path.join(self.assets_dir, "overlay_blush.png"))
        self.img_blush = ImageTk.PhotoImage(blush_raw.resize((self.win_w, self.win_h), Image.Resampling.LANCZOS))

        angry_raw = Image.open(os.path.join(self.assets_dir, "overlay_angry.png"))
        self.img_angry = ImageTk.PhotoImage(angry_raw.resize((self.win_w, self.win_h), Image.Resampling.LANCZOS))

        shock_raw = Image.open(os.path.join(self.assets_dir, "overlay_shock.png"))
        self.img_shock = ImageTk.PhotoImage(shock_raw.resize((self.win_w, self.win_h), Image.Resampling.LANCZOS))

    def set_emotion(self, emotion: str):
        self.emotion = emotion.lower().strip()
        self.braid_vel += 4.0

    def set_mouth_openness(self, openness: float):
        self.mouth_openness = max(0.0, min(1.0, openness))
        if openness > 0.3:
            self.braid_vel += (openness * 1.2)

    def _render_loop(self):
        """Main 30 FPS physics, IPC message check, and deformation render loop."""
        # 1. Process incoming UDP state packets
        try:
            while True:
                data, _ = self.sock.recvfrom(512)
                msg = json.loads(data.decode("utf-8"))
                if "emotion" in msg:
                    self.set_emotion(msg["emotion"])
                if "mouth" in msg:
                    self.set_mouth_openness(msg["mouth"])
        except (BlockingIOError, socket.error):
            pass

        now = time.time()
        dt = min(0.05, now - self.last_frame_time)
        self.last_frame_time = now
        t = now - self.start_time

        # 2. Procedural Breathing & Subtle Head Tilt/Sway (THA3 Pose simulation)
        breath_y = int(math.sin(t * 1.8) * 2.0)
        head_sway_x = int(math.sin(t * 1.2) * 1.5)

        # 3. Natural Blinking Logic
        if now >= self.next_blink_time:
            self.is_blinking = True
            self.blink_end_time = now + 0.14
            self.next_blink_time = now + random.uniform(2.8, 5.0)

        if self.is_blinking and now >= self.blink_end_time:
            self.is_blinking = False

        # 4. Spring Physics for Hair/Braid
        force = -self.braid_stiffness * self.braid_angle
        self.braid_vel += force * dt
        self.braid_vel *= self.braid_damping
        self.braid_angle += self.braid_vel * dt
        braid_offset_x = int(self.braid_angle * 1.5 + math.sin(t * 2.2) * 1.5)

        # -----------------------------------------------------------------
        # Redraw Layers (Live Talking Head Composite)
        # -----------------------------------------------------------------
        self.canvas.delete("all")

        # Layer 1: Base Character Body
        self.canvas.create_image(head_sway_x, breath_y, image=self.img_base, anchor="nw")

        # Layer 2: Eyes (Blink state or happy squint)
        if self.is_blinking or self.emotion == "happy":
            self.canvas.create_image(self.eyes_x + head_sway_x, self.eyes_y + breath_y, image=self.img_eyes_closed, anchor="nw")

        # Layer 3: Mouth Lip-Sync
        if self.mouth_openness > 0.25:
            self.canvas.create_image(self.mouth_x + head_sway_x, self.mouth_y + breath_y, image=self.img_mouth_open, anchor="nw")

        # Layer 4: Braid Hair Physics Layer
        braid_scaled = self.braid_raw.resize((self.braid_w, self.braid_h), Image.Resampling.LANCZOS)
        self.cur_braid_img = ImageTk.PhotoImage(braid_scaled)
        self.canvas.create_image(self.braid_anchor_x + braid_offset_x + head_sway_x, self.braid_anchor_y + breath_y, image=self.cur_braid_img, anchor="nw")

        # Layer 5: Dynamic Emotion Overlays
        if self.emotion in ["blush", "happy"]:
            self.canvas.create_image(head_sway_x, breath_y, image=self.img_blush, anchor="nw")
        elif self.emotion == "angry":
            self.canvas.create_image(head_sway_x, breath_y, image=self.img_angry, anchor="nw")
        elif self.emotion == "shock":
            self.canvas.create_image(head_sway_x, breath_y, image=self.img_shock, anchor="nw")

        # Next frame
        self.root.after(33, self._render_loop)

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    engine = AvatarEngine()
    print("AvatarEngine started! Floating on desktop.")
    engine.run()
