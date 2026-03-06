import asyncio
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from .engine import RealTimeSTTEngine
from typing import List

app = FastAPI()
engine = RealTimeSTTEngine()


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.session_text = ""  # 누적 텍스트 (공백 제거 버전)

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        raw = "".join(s["text"] for s in message.get("subtitles", [])).strip()
        if not raw:
            return

        new_norm = raw.replace(" ", "")
        if not new_norm:
            return

        existing = self.session_text

        # 1) 완전 포함: 새 텍스트가 이미 누적 텍스트에 포함되면 무시
        if new_norm in existing:
            return

        # 2) suffix-prefix overlap: 20자 제한 제거, 전체 범위 검색
        #    가장 긴 겹침을 먼저 찾아서 break (효율적)
        overlap = 0
        max_check = min(len(existing), len(new_norm))
        for i in range(max_check, 0, -1):
            if existing[-i:] == new_norm[:i]:
                overlap = i
                break

        added = new_norm[overlap:]
        if not added:
            return

        # 누적 (최근 300자)
        self.session_text += added
        if len(self.session_text) > 300:
            self.session_text = self.session_text[-300:]

        # 전송 (실패한 연결 정리)
        dead = []
        for conn in self.active_connections:
            try:
                await conn.send_json({"subtitles": [{"text": added}]})
            except Exception:
                dead.append(conn)
        for conn in dead:
            self.active_connections.remove(conn)

manager = ConnectionManager()

@app.websocket("/ws/stt")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    audio_buffer = bytearray()
    
    # 5080용 최적 윈도우 (1초 데이터, 0.5초 이동)
    CHUNK_STEP = int(16000 * 2 * 0.5) 
    MAX_BUFFER = int(16000 * 2 * 1.0) 
    
    try:
        while True:
            data = await websocket.receive_bytes()
            audio_buffer.extend(data)
            
            if len(audio_buffer) >= MAX_BUFFER:
                audio_np = np.frombuffer(audio_buffer, dtype=np.int16).astype(np.float32) / 32768.0
                results, _ = engine.transcribe_chunk(audio_np)
                
                if results:
                    await manager.broadcast({"subtitles": results})
                
                audio_buffer = audio_buffer[CHUNK_STEP:]

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        manager.disconnect(websocket)
