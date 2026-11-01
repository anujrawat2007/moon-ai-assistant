import tkinter as tk
import threading
import time

class AnimeAvatarOverlay:
    """
    Lightweight, transparent, always-on-top desktop anime character widget.
    Consumes < 30 MB RAM and 0% GPU.
    """
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Lumina Avatar")
        
        # Window settings: borderless, always on top
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)
        
        # Transparent background color key
        self.trans_color = "#123456"
        self.root.wm_attributes("-transparentcolor", self.trans_color)
        self.root.config(bg=self.trans_color)
        
        # Default position: bottom right corner of the screen
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        window_width, window_height = 200, 250
        x = screen_width - window_width - 40
        y = screen_height - window_height - 60
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        
        # Draggable setup
        self._drag_data = {"x": 0, "y": 0}
        self.canvas = tk.Canvas(
            self.root, 
            width=window_width, 
            height=window_height, 
            bg=self.trans_color, 
            highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True)
        
        self.canvas.bind("<ButtonPress-1>", self.on_start_drag)
        self.canvas.bind("<B1-Motion>", self.on_drag)

        # Draw a cute placeholder avatar
        self.current_emotion = "happy"
        self.is_talking = False
        self.draw_avatar()

    def on_start_drag(self, event):
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def on_drag(self, event):
        deltax = event.x - self._drag_data["x"]
        deltay = event.y - self._drag_data["y"]
        x = self.root.winfo_x() + deltax
        y = self.root.winfo_y() + deltay
        self.root.geometry(f"+{x}+{y}")

    def draw_avatar(self):
        """Draws dynamic vector-style cute anime avatar based on emotion & talking state."""
        self.canvas.delete("all")
        
        # Head / Hair
        self.canvas.create_oval(30, 20, 170, 160, fill="#FFD1DC", outline="#FFB7C5", width=3) # Soft hair
        self.canvas.create_oval(45, 45, 155, 155, fill="#FFF0E6", outline="#E0C0A8", width=2) # Face
        
        # Eyes
        if self.current_emotion == "happy":
            # Happy arched eyes ^ ^
            self.canvas.create_arc(60, 75, 90, 100, start=0, extent=180, style=tk.ARC, width=3, outline="#5C4033")
            self.canvas.create_arc(110, 75, 140, 100, start=0, extent=180, style=tk.ARC, width=3, outline="#5C4033")
        elif self.current_emotion == "surprised":
            # Wide eyes O O
            self.canvas.create_oval(65, 75, 85, 100, fill="#4A90E2", outline="#2C3E50", width=2)
            self.canvas.create_oval(115, 75, 135, 100, fill="#4A90E2", outline="#2C3E50", width=2)
        else:
            # Cute normal eyes
            self.canvas.create_oval(65, 80, 85, 100, fill="#4A90E2", outline="#2C3E50", width=2)
            self.canvas.create_oval(115, 80, 135, 100, fill="#4A90E2", outline="#2C3E50", width=2)
            # Highlights
            self.canvas.create_oval(70, 83, 76, 89, fill="white", outline="white")
            self.canvas.create_oval(120, 83, 126, 89, fill="white", outline="white")

        # Cheeks (Blushing)
        self.canvas.create_oval(50, 105, 68, 117, fill="#FFB7C5", outline="")
        self.canvas.create_oval(132, 105, 150, 117, fill="#FFB7C5", outline="")

        # Mouth
        if self.is_talking:
            # Open mouth
            self.canvas.create_oval(92, 115, 108, 132, fill="#E74C3C", outline="#C0392B", width=2)
        else:
            # Small smile
            self.canvas.create_arc(92, 110, 108, 125, start=200, extent=140, style=tk.ARC, width=2, outline="#5C4033")

        # Name Badge
        self.canvas.create_rectangle(60, 165, 140, 185, fill="#9B59B6", outline="white", width=1)
        self.canvas.create_text(100, 175, text="Lumina ✨", fill="white", font=("Helvetica", 9, "bold"))

    def set_emotion(self, emotion: str):
        self.current_emotion = emotion
        self.draw_avatar()

    def set_talking(self, talking: bool):
        self.is_talking = talking
        self.draw_avatar()

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    overlay = AnimeAvatarOverlay()
    print("Overlay running. You can click & drag Lumina anywhere on your screen!")
    overlay.run()
