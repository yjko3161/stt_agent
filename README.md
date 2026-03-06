# Real-time STT & Subtitle System (RTX 5080 Optimized)

PC 시스템 오디오를 실시간으로 캡처하여 한국어 음성 인식(STT) 후 자막을 표시하는 시스템.

---

## System Architecture

```
stt_agent/
├── server/app/
│   ├── main.py          # FastAPI + WebSocket 서버 (중복 제거 로직 포함)
│   └── engine.py        # SenseVoice STT 엔진 (CUDA)
├── client_test/
│   ├── master_control.py   # 통합 Master Control GUI (메인)
│   ├── gui_subtitle.py     # 독립 자막 오버레이 (유틸)
│   └── system_audio_test.py # 독립 오디오 캡처 테스트 (유틸)
├── models/              # 로컬 모델 캐시 (SenseVoice)
├── .venv/               # Python 가상환경
├── start_all.bat        # 원클릭 실행
├── run_server.bat       # 서버만 실행
├── run_master_control.bat # Master Control만 실행
└── run_gui.bat          # 자막 오버레이만 실행
```

---

## Core Components

### STT Engine (`server/app/engine.py`)
- **Model:** Alibaba SenseVoice Small (`iic/SenseVoiceSmall`)
- **Hub:** ModelScope
- **Device:** CUDA (RTX 5080 기준 RTF 0.04)
- **Language:** Korean (`ko`)
- 비음성 태그 자동 제거 (`[MUSIC]`, `<|ko|>`, `<|Speech|>` 등)

### WebSocket Server (`server/app/main.py`)
- **Endpoint:** `ws://0.0.0.0:{port}/ws/stt`
- **Protocol:** Client sends binary PCM int16, Server responds JSON
- **Audio Buffer:** 1.0s window, 0.5s sliding step (16kHz, mono)
- **Echo Prevention (server-side):**
  1. 공백 제거 후 정규화 비교
  2. 완전 포함 체크 (새 텍스트가 누적 텍스트에 포함되면 무시)
  3. suffix-prefix overlap 전체 범위 검색 (제한 없음)
  4. 누적 300자 유지, dead connection 자동 정리

```
Client → Server:  raw bytes (int16 PCM, 16kHz mono)
Server → Client:  {"subtitles": [{"text": "인식된 텍스트"}]}
```

### Master Control GUI (`client_test/master_control.py`)

4개 클래스, 단일 파일 구조:

| Class | Role |
|---|---|
| `ServerManager` | uvicorn 서브프로세스 start/stop/is_alive |
| `AudioStreamer` | WASAPI 루프백 캡처 + WebSocket 스트리밍 (자동 재연결) |
| `SubtitleOverlay` | 투명 자막 오버레이 (1400x150, 노란 글씨, 3초 자동 소멸) |
| `MasterControlGUI` | 메인 Tkinter 앱 (위 3개 통합 제어) |

**GUI Layout:**
```
+----------------------------------------------------+
| STT Master Control                                  |
+----------------------------------------------------+
| Server Control                                      |
| [Start Server] [Stop Server]  Port:[8000]  [ONLINE] |
+----------------------------------------------------+
| STT Audio Capture                                   |
| [Start STT]    [Stop STT]              [RUNNING]    |
+----------------------------------------------------+
| Subtitle Overlay                                    |
| [Hide Subtitle]                        [VISIBLE]    |
+----------------------------------------------------+
| System Logs                                         |
| +------------------------------------------------+ |
| | [19:30:01] System initialized.                 | |
| | [19:30:02] [Server] Starting uvicorn...        | |
| +------------------------------------------------+ |
| Ready                                               |
+----------------------------------------------------+
```

**Key Features:**
- Server / STT / Subtitle 각각 독립 Start/Stop
- Port GUI에서 변경 가능 (서버 중지 상태에서)
- WebSocket 끊김 시 2초 후 자동 재접속
- 서버 종료 시 STT 자동 중지
- 1초 주기 상태 자동 감지 (비정상 종료 시 버튼 복원)
- Thread-safe Queue 기반 GUI 업데이트
- Client-side dedup (직전 텍스트와 동일하면 skip)

---

## Audio Capture Specs

| Item | Value |
|---|---|
| Sample Rate | 16,000 Hz |
| Channels | 1 (mono) |
| Chunk Size | 3,200 frames (0.2s) |
| Capture Method | WASAPI Loopback (soundcard library) |
| Format | float32 -> int16 변환 후 전송 |

---

## Quick Start

```bash
# 방법 1: 원클릭
start_all.bat

# 방법 2: 직접 실행
python client_test/master_control.py

# 방법 3: 서버/클라이언트 분리 실행
run_server.bat          # 터미널 1
run_gui.bat             # 터미널 2
```

Master Control GUI에서:
1. Port 설정 (기본 8000)
2. **Start Server** -> 로그에서 uvicorn 기동 확인, 상태 ONLINE
3. **Start STT** -> 오디오 캡처 시작, 음성 인식 결과 자막 표시
4. **Hide/Show Subtitle** 토글
5. 종료: Stop STT -> Stop Server 또는 X 버튼 (자동 정리)

---

## Dev Environment

- **GPU:** RTX 5080 (Blackwell)
- **PyTorch:** 2.6.0+cu128 (Nightly) - RTX 50 series 호환
- **Python:** 3.12+ (가상환경 `.venv`)
- **Key Libraries:** FastAPI, uvicorn, websockets, soundcard, numpy, funasr, torch

---

> **GitHub:** [https://github.com/yjko3161/stt_agent](https://github.com/yjko3161/stt_agent)
