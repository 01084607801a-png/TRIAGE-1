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
import tkintermapview


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
    env = os.environ.copy()
    env["TRIAGE_DESKTOP"] = "1"
    proc = subprocess.Popen([sys.executable, app_py], env=env)
    if not wait_server(BASE_URL):
        proc.terminate()
        raise RuntimeError("Flask 서버 시작 실패")
    return proc


class TriageDesktopApp:
    def __init__(self, root, server_proc):
        self.root = root
        self.server_proc = server_proc
        self.root.title("TRIAGE-1 Desktop")
        self.root.geometry("1400x740")

        self.injuries_options = ["두부/경부", "안면", "흉부", "복부", "척추", "상지", "하지"]
        self.injury_vars = {}

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _fetch_current_location(self):
        """IP 기반 대략적인 현재 위치 감지"""
        try:
            resp = requests.get("http://ip-api.com/json/", timeout=3)
            data = resp.json()
            if data["status"] == "success":
                return data["lat"], data["lon"]
        except Exception:
            pass
        # Fallback: 서울시청
        return 37.5665, 126.9780

    def _fetch_address(self, lat, lng):
        """위도/경도를 도로명/지번 주소로 변환 (OpenStreetMap Nominatim)"""
        try:
            url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lng}&format=json&accept-language=ko"
            headers = {'User-Agent': 'Triage-Desktop-App'}
            resp = requests.get(url, headers=headers, timeout=3)
            data = resp.json()
            if "display_name" in data:
                # 서양식 주소(작은 단위 -> 큰 단위)를 한국식(큰 단위 -> 작은 단위)으로 역순 정렬
                parts = data["display_name"].split(", ")
                filtered = [p for p in parts if not p.isdigit() and "대한민국" not in p and "South Korea" not in p]
                return " ".join(reversed(filtered))
        except Exception:
            pass
        return "주소 확인 불가"

    def update_location_display(self, lat, lng, move_map=False):
        """위도/경도 변수 업데이트 및 비동기로 주소를 가져와 라벨에 표시"""
        self.lat_var.set(f"{lat:.4f}")
        self.lng_var.set(f"{lng:.4f}")
        self.location_display_var.set(f"로딩 중...")
        
        if move_map:
            self.map_widget.set_position(lat, lng)
            if hasattr(self, 'marker') and self.marker:
                self.marker.delete()
            self.marker = self.map_widget.set_marker(lat, lng, text="현재 위치")
            
        def fetch_task():
            address = self._fetch_address(lat, lng)
            # 메인 스레드(UI) 업데이트
            self.root.after(0, lambda: self.location_display_var.set(address))
            
        threading.Thread(target=fetch_task, daemon=True).start()

    def search_address(self):
        address = self.location_display_var.get().strip()
        if not address or address == "주소 확인 불가" or "로딩 중" in address:
            messagebox.showwarning("주소 검색", "검색할 주소를 입력하거나 현위치를 먼저 확인하세요.")
            return
            
        self.location_display_var.set("주소 검색 중...")
        self.root.update()
        
        def fetch():
            try:
                url = f"https://nominatim.openstreetmap.org/search?q={address}&format=json&limit=1&accept-language=ko"
                headers = {'User-Agent': 'Triage-Desktop-App'}
                resp = requests.get(url, headers=headers, timeout=3)
                data = resp.json()
                if data and len(data) > 0:
                    lat = float(data[0]["lat"])
                    lng = float(data[0]["lon"])
                    self.root.after(0, lambda: self.update_location_display(lat, lng, move_map=True))
                else:
                    self.root.after(0, lambda: self.location_display_var.set(f"{address} (검색 실패)"))
            except Exception:
                self.root.after(0, lambda: self.location_display_var.set(f"{address} (오류 발생)"))
                
        threading.Thread(target=fetch, daemon=True).start()

    def refresh_current_location(self):
        self.location_display_var.set("IP 현위치 탐색 중...")
        self.root.update()
        def fetch():
            lat, lng = self._fetch_current_location()
            self.root.after(0, lambda: self.update_location_display(lat, lng, move_map=True))
        threading.Thread(target=fetch, daemon=True).start()

    def update_map_from_coords(self, event=None):
        try:
            lat = float(self.lat_var.get())
            lng = float(self.lng_var.get())
            self.update_location_display(lat, lng, move_map=True)
        except ValueError:
            pass

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

        # --- 메인 보드 상단: 주소 검색 및 현위치 (Row 3) ---
        addr_frame = ttk.Frame(frame)
        addr_frame.grid(row=3, column=0, columnspan=4, sticky="we", pady=(10, 8))
        
        ttk.Label(addr_frame, text="주소 검색:", font=("Malgun Gothic", 10, "bold")).pack(side="left")
        self.location_display_var = tk.StringVar(value="로딩 중...")
        addr_entry = ttk.Entry(addr_frame, textvariable=self.location_display_var, width=32)
        addr_entry.pack(side="left", padx=5)
        addr_entry.bind("<Return>", lambda e: self.search_address())
        
        ttk.Button(addr_frame, text="검색", command=self.search_address).pack(side="left", padx=2)
        ttk.Button(addr_frame, text="현위치 새로고침", command=self.refresh_current_location).pack(side="left", padx=2)

        ttk.Label(frame, text="Latitude").grid(row=4, column=0, sticky="w", pady=4)
        self.lat_var = tk.StringVar()
        lat_entry = ttk.Entry(frame, textvariable=self.lat_var, width=15)
        lat_entry.grid(row=4, column=1, sticky="w", pady=4)
        lat_entry.bind("<Return>", self.update_map_from_coords)

        ttk.Label(frame, text="Longitude").grid(row=4, column=2, sticky="w", pady=4)
        self.lng_var = tk.StringVar()
        lng_entry = ttk.Entry(frame, textvariable=self.lng_var, width=15)
        lng_entry.grid(row=4, column=3, sticky="w", pady=4)
        lng_entry.bind("<Return>", self.update_map_from_coords)

        ttk.Label(frame, text="손상 부위 (중복 선택)").grid(row=5, column=0, columnspan=4, sticky="w", pady=(10, 4))
        injury_frame = ttk.Frame(frame)
        injury_frame.grid(row=6, column=0, columnspan=4, sticky="w")
        for idx, name in enumerate(self.injuries_options):
            v = tk.BooleanVar(value=(name == "두부/경부"))
            self.injury_vars[name] = v
            ttk.Checkbutton(injury_frame, text=name, variable=v).grid(row=idx // 4, column=idx % 4, padx=8, pady=3, sticky="w")

        ttk.Button(frame, text="추천 실행", command=self.run_recommendation).grid(row=7, column=0, pady=(12, 8), sticky="w")

        self.output = ScrolledText(frame, width=100, height=28)
        self.output.grid(row=8, column=0, columnspan=4, sticky="nsew", pady=(6, 0))

        # --- 지도 위젯 추가 ---
        self.map_widget = tkintermapview.TkinterMapView(frame, width=500, height=600, corner_radius=5)
        self.map_widget.grid(row=0, column=4, rowspan=9, padx=20, pady=10, sticky="nsew")
        
        # 랙 방지를 위한 구글 맵 타일 서버 사용 (속도 개선)
        self.map_widget.set_tile_server("https://mt0.google.com/vt/lyrs=m&hl=ko&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)

        # 현재 위치 감지 (IP 기반) 및 초기화
        # 네트워크 불안정 시 즉시 기본 위치로 초기화하고, 위치 탐색은 백그라운드로 처리합니다.
        self.update_location_display(37.5665, 126.9780, move_map=True)
        threading.Thread(target=self.refresh_current_location, daemon=True).start()

        # 지도 우클릭 시 이벤트 바인딩 (핀 이동 및 좌표 변경)
        self.map_widget.add_right_click_menu_command(label="여기를 현위치로 설정",
                                                     command=self.on_map_right_click,
                                                     pass_coords=True)

        frame.rowconfigure(8, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)
        frame.columnconfigure(4, weight=2)

    def on_map_right_click(self, coords):
        lat, lng = coords
        self.update_location_display(lat, lng, move_map=True)
        self.output.insert(tk.END, f"📌 위치가 변경되었습니다: {lat:.4f}, {lng:.4f}\n")
        self.output.see(tk.END)

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
                route_dist = h.get('route_distance_km', h.get('dist_km', 0))
                travel_time = h.get('travel_time_min')
                travel_time_text = f" / {round(travel_time)}분" if travel_time is not None else ""
                self.output.insert(tk.END, f"  거리: {route_dist:.1f}km{travel_time_text} | 등급: {h.get('level')} | 병상: {bed_text}\n")
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
    root.lift()
    root.attributes('-topmost', True)
    root.after(100, lambda: root.attributes('-topmost', False))
    root.mainloop()


if __name__ == "__main__":
    main()
