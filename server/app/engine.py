import os
import re
import numpy as np
import torch
from funasr import AutoModel

class RealTimeSTTEngine:
    def __init__(self, model_name="iic/SenseVoiceSmall", device="cuda"):
        # 한글 경로 문제(Illegal byte sequence) 해결을 위한 절대 경로 설정
        # 현재 실행 위치를 기준으로 models 폴더 사용
        self.base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.models_dir = os.path.join(self.base_dir, "models")
        
        if not os.path.exists(self.models_dir):
            os.makedirs(self.models_dir, exist_ok=True)

        # 환경 변수 강제 고정
        os.environ["MODELSCOPE_CACHE"] = self.models_dir
        os.environ["XDG_CACHE_HOME"] = self.models_dir
        os.environ["HF_HOME"] = self.models_dir

        print(f"\n[Engine] Initializing SenseVoice on {device}...")
        print(f"[Engine] Cache Directory: {self.models_dir}")
        
        try:
            self.model = AutoModel(
                model=model_name,
                device=device,
                disable_update=True,
                hub="modelscope"
            )
            print("[Engine] SenseVoice Model Loaded Successfully!")
        except Exception as e:
            print(f"\n[Engine Error] Model loading failed: {e}")
            import traceback
            traceback.print_exc()

    def transcribe_chunk(self, audio_data, language="ko", task="transcribe"):
        if len(audio_data) < 1600:
            return [], None

        try:
            res = self.model.generate(
                input=audio_data,
                cache={},
                language=language,
                use_itn=False,
                batch_size=1,
                disable_pbar=True # 진행바 삭제
            )
            
            results = []
            if res and len(res) > 0:
                raw_text = res[0]['text'].strip()

                # 1. 모든 특수 태그 제거 ([MUSIC], <|ko|>, <|Speech|> 등)
                clean_text = re.sub(r'\[.*?\]', '', raw_text) # [ 태그 ] 제거
                clean_text = re.sub(r'<\|.*?\|>', '', clean_text) # <| 태그 |> 제거
                clean_text = clean_text.strip()

                # 2. 불필요한 공백 및 반복 문구 정리
                if clean_text:
                    results.append({
                        "text": clean_text,
                        "start": 0,
                        "end": len(audio_data) / 16000
                    })

            
            return results, None
        except Exception as e:
            print(f"[Engine Error] Transcribe failed: {e}")
            return [], None
