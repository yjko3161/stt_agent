import asyncio
import websockets
import json
import numpy as np
import soundcard as sc
import threading
from queue import Queue

SAMPLING_RATE = 16000
audio_queue = Queue()

def record_worker():
    try:
        # 루프백 마이크(스피커 캡처) 선택
        mics = sc.all_microphones(include_loopback=True)
        loopback = next((m for m in mics if "loopback" in m.name.lower() or "루프백" in m.name.lower()), mics[0])
        print(f"[Audio] Recording from: {loopback.name}")
        with loopback.recorder(samplerate=SAMPLING_RATE, channels=1) as recorder:
            while True:
                data = recorder.record(numframes=6400) # 0.4s chunk
                audio_queue.put(data)
    except Exception as e: print(f"[Audio Error] {e}")

async def stream_to_server():
    uri = "ws://localhost:8000/ws/stt"
    while True:
        try:
            async with websockets.connect(uri) as websocket:
                print("[Stream] Connected to server.")
                while True:
                    if not audio_queue.empty():
                        data = audio_queue.get()
                        chunk_int16 = (data[:, 0] * 32767).astype(np.int16)
                        await websocket.send(chunk_int16.tobytes())
                    await asyncio.sleep(0.01)
        except: await asyncio.sleep(2)

if __name__ == "__main__":
    threading.Thread(target=record_worker, daemon=True).start()
    asyncio.run(stream_to_server())
