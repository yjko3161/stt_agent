import asyncio
import websockets
import json
import threading
import tkinter as tk
from queue import Queue
import time

class SubtitleOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Real-time Subtitles")
        self.root.attributes("-alpha", 0.85)
        self.root.attributes("-topmost", True)
        self.root.overrideredirect(True)
        
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width, height = 1400, 180
        x, y = (screen_width - width) // 2, screen_height - 220
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.configure(bg='black')
        
        self.label = tk.Label(
            self.root, text="", font=("Malgun Gothic", 32, "bold"), 
            fg="#FFFF00", bg="black", wraplength=1300, justify="center"
        )
        self.label.pack(expand=True, pady=10)
        
        self.queue = Queue()
        self.last_text = ""
        self.last_update_time = time.time()
        self.update_gui()

    def update_gui(self):
        try:
            latest_text = None
            while not self.queue.empty():
                latest_text = self.queue.get_nowait()
            
            if latest_text and latest_text != self.last_text:
                self.label.config(text=latest_text)
                self.last_text = latest_text
                self.last_update_time = time.time()
            
            if time.time() - self.last_update_time > 2.5:
                self.label.config(text="")
                self.last_text = ""
        except: pass
        self.root.after(10, self.update_gui)

    def run(self): self.root.mainloop()

async def listen_server(gui_queue):
    uri = "ws://localhost:8000/ws/stt"
    while True:
        try:
            async with websockets.connect(uri) as websocket:
                print("[GUI] Connected to server.")
                while True:
                    response = await websocket.recv()
                    data = json.loads(response)
                    subs = data.get("subtitles", [])
                    if subs:
                        gui_queue.put(" ".join([s['text'] for s in subs]))
        except:
            await asyncio.sleep(2)

if __name__ == "__main__":
    overlay = SubtitleOverlay()
    threading.Thread(target=lambda: asyncio.run(listen_server(overlay.queue)), daemon=True).start()
    overlay.run()
