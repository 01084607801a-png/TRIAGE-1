"""TRIAGE-1 Desktop client (Tkinter).

Run this file to launch a native desktop UI and test recommendations
without manually opening the browser.
"""

import os
import subprocess
import sys
import time
import urllib.request
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from tkinter.scrolledtext import ScrolledText
import threading

import requests


BASE_URL = "http://127.0.0.1:5000"


def wait_server(url, timeout=25):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status in (200, 404):
                    return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def start_flask_server():
    app_py = os.path.join(os.path.dirname(__file__), "app.py")
    proc = subprocess.Popen([sys.executable, app_py])
    if not wait_server(BASE_URL):
        proc.terminate()
        raise RuntimeError("Flask 서버 시작 실패")
    return proc


class TriageDesktopApp:
    def __init__(self, root, server_proc):
        self.root = root
        self.server_proc = server_proc
        self.root.title("TRIAGE-1 Desktop")
        self.root.geometry("980x740")

        self.injuries_options = ["두부/경부", "안면", "흉부", "복부", "척추", "상지", "하지"]
        self.injury_vars = {}

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self):
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="TRIAGE-1 Desktop 테스트", font=("Malgun Gothic", 14, "bold")).grid(row=0, column=0, columnspan=4, sticky="w")

        ttk.Label(frame, text="GCS Motor").grid(row=1, column=0, sticky="w", pady=(10, 4))
        self.gcs_var = tk.StringVar(value="6")
        ttk.Spinbox(frame, from_=2, to=6, textvariable=self.gcs_var, width=10).grid(row=1, column=1, sticky="w", pady=(10, 4))

        ttk.Label(frame, text="SBP (mmHg)").grid(row=1, column=2, sticky="w", pady=(10, 4))
        self.sbp_var = tk.StringVar(value="110")
        ttk.Spinbox(frame, from_=50, to=250, textvariable=self.sbp_var, width=10).grid(row=1, column=3, sticky="w", pady=(10, 4))

        ttk.Label(frame, text="RR (/분)").grid(row=2, column=0, sticky="w", pady=4)
        self.rr_var = tk.StringVar(value="18")
        ttk.Spinbox(frame, from_=8, to=50, textvariable=self.rr_var, width=10).grid(row=2, column=1, sticky="w", pady=4)

        ttk.Label(frame, text="Age (세)").grid(row=2, column=2, sticky="w", pady=4)
        self.age_var = tk.StringVar(value="45")
        ttk.Spinbox(frame, from_=0, to=150, textvariable=self.age_var, width=10).grid(row=2, column=3, sticky="w", pady=4)

        ttk.Label(frame, text="Latitude").grid(row=3, column=0, sticky="w", pady=4)
        self.lat_var = tk.StringVar(value="37.5665")
        ttk.Entry(frame, textvariable=self.lat_var, width=18).grid(row=3, column=1, sticky="w", pady=4)

        ttk.Label(frame, text="Longitude").grid(row=3, column=2, sticky="w", pady=4)
        self.lng_var = tk.StringVar(value="126.9780")
        ttk.Entry(frame, textvariable=self.lng_var, width=18).grid(row=3, column=3, sticky="w", pady=4)

        ttk.Label(frame, text="손상 부위 (중복 선택)").grid(row=4, column=0, columnspan=4, sticky="w", pady=(10, 4))
        injury_frame = ttk.Frame(frame)
        injury_frame.grid(row=5, column=0, columnspan=4, sticky="w")
        for idx, name in enumerate(self.injuries_options):
            v = tk.BooleanVar(value=(name == "두부/경부"))
            self.injury_vars[name] = v
            ttk.Checkbutton(injury_frame, text=name, variable=v).grid(row=idx // 4, column=idx % 4, padx=8, pady=3, sticky="w")

        ttk.Button(frame, text="추천 실행", command=self.run_recommendation).grid(row=6, column=0, pady=(12, 8), sticky="w")

        self.output = ScrolledText(frame, width=120, height=28)
        self.output.grid(row=7, column=0, columnspan=4, sticky="nsew", pady=(6, 0))

        frame.rowconfigure(7, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)

    def run_recommendation(self):
        injuries = [k for k, v in self.injury_vars.items() if v.get()]
        if not injuries:
            messagebox.showwarning("입력 확인", "최소 1개 손상 부위를 선택하세요.")
            return

        try:
            payload = {
                "gcs_motor": int(self.gcs_var.get()),
                "sbp": int(self.sbp_var.get()),
                "rr": int(self.rr_var.get()),
                "age": int(self.age_var.get()),
                "lat": float(self.lat_var.get()),
                "lng": float(self.lng_var.get()),
                "injuries": injuries,
            }
        except ValueError:
            messagebox.showerror("입력 오류", "숫자 입력 필드를 확인하세요.")
            return

        # 별도 스레드에서 요청 처리 (UI 블로킹 방지)
        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, "🔄 병원 검색 중...\n⏳ 30초 이상 소요될 수 있습니다.\n\n")
        self.root.update()
        
        thread = threading.Thread(target=self._fetch_recommendation, args=(payload,))
        thread.daemon = True
        thread.start()

    def _fetch_recommendation(self, payload):
        try:
            resp = requests.post(f"{BASE_URL}/api/recommend", json=payload, timeout=60)
            self.output.delete("1.0", tk.END)
            
            if resp.status_code != 200:
                data = resp.json()
                self.output.insert(tk.END, f"❌ 오류: {data.get('error')}\n상세: {data.get('detail', '')}\n")
                return

            data = resp.json()
            matched = data.get("matched", [])

            self.output.insert(tk.END, f"✓ CDC 분류: {'🔴 고위험(RED)' if data['field_triage']['high_risk'] else '🟡 중등도(YELLOW)'}\n")
            self.output.insert(tk.END, f"✓ 검색 반경: {data.get('search_radius_km', 50)}km\n")
            
            ml_info = data.get("ml_model", {})
            if ml_info.get("loaded"):
                self.output.insert(tk.END, f"✓ ML 모델(Random Forest): {ml_info.get('accuracy')*100:.1f}% 정확도\n")
            
            self.output.insert(tk.END, "\n")

            if not matched:
                self.output.insert(tk.END, "⚠️ 추천 가능한 병원이 없습니다.\n")
                self.output.insert(tk.END, "좌표/손상 조건을 조정해 다시 시도하세요.\n")
                return

            for i, h in enumerate(matched, start=1):
                hvec = h.get("hvec")
                hvoc = h.get("hvoc")
                bed_text = f"응급:{hvec if hvec is not None else '정보없음'} | 수술:{hvoc if hvoc is not None else '정보없음'}"
                ml_prob = h.get("ml_rtc_probability")
                
                self.output.insert(tk.END, f"[{i}순위] {h.get('name')}\n")
                self.output.insert(tk.END, f"  거리: {h.get('dist_km', 0):.1f}km | 등급: {h.get('level')} | 병상: {bed_text}\n")
                if ml_prob is not None:
                    self.output.insert(tk.END, f"  점수: {h.get('score'):.3f} (ML확률: {ml_prob:.1%})\n")
                else:
                    self.output.insert(tk.END, f"  점수: {h.get('score'):.3f}\n")
                self.output.insert(tk.END, f"  사유: {h.get('reason')}\n\n")

        except requests.exceptions.Timeout:
            self.output.delete("1.0", tk.END)
            self.output.insert(tk.END, "❌ 시간 초과 (60초)\n")
            self.output.insert(tk.END, "Flask 서버 또는 NEMC API가 응답하지 않습니다.\n\n")
            self.output.insert(tk.END, "[해결 방법]\n")
            self.output.insert(tk.END, "1. 네트워크 연결 확인\n")
            self.output.insert(tk.END, "2. app.py Flask 서버 재시작\n")
            self.output.insert(tk.END, "3. 좌표가 유효한지 확인\n")
        except Exception as exc:
            self.output.delete("1.0", tk.END)
            self.output.insert(tk.END, f"❌ 요청 실패\n오류: {exc}\n")

    def on_close(self):
        try:
            if self.server_proc and self.server_proc.poll() is None:
                self.server_proc.terminate()
        finally:
            self.root.destroy()


def main():
    server_proc = start_flask_server()
    root = tk.Tk()
    TriageDesktopApp(root, server_proc)
    root.mainloop()


if __name__ == "__main__":
    main()
