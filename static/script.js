// GCS Motor Score Selection
document.querySelectorAll('.gcs-buttons button').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.gcs-buttons button').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('gcs_motor').value = btn.dataset.value;
    });
});

// Age checkbox
document.getElementById('age65').addEventListener('change', (e) => {
    document.getElementById('age').value = e.target.checked ? 70 : 45;
});

// GPS Location Detection
function getLocation() {
    const statusEl = document.getElementById('location-status');
    const latEl = document.getElementById('lat');
    const lngEl = document.getElementById('lng');

    if (navigator.geolocation) {
        statusEl.textContent = '📍 위치 감지 중...';
        navigator.geolocation.getCurrentPosition(
            (pos) => {
                latEl.value = pos.coords.latitude.toFixed(6);
                lngEl.value = pos.coords.longitude.toFixed(6);
                statusEl.textContent = `📍 위치 자동 감지됨 (${pos.coords.latitude.toFixed(4)}, ${pos.coords.longitude.toFixed(4)})`;
            },
            (err) => {
                statusEl.textContent = '⚠️ 위치 감지 실패 - 수동 입력하세요';
                console.error('Geolocation error:', err);
            },
            { enableHighAccuracy: true, timeout: 10000 }
        );
    } else {
        statusEl.textContent = '⚠️ GPS를 지원하지 않는 브라우저입니다';
    }
}

// Initialize location detection on load
window.addEventListener('load', getLocation);

// Hospital Recommendation
document.getElementById('recommendBtn').addEventListener('click', async () => {
    const gcs_motor = document.getElementById('gcs_motor').value;
    const sbp = document.getElementById('sbp').value;
    const rr = document.getElementById('rr').value;
    const age = document.getElementById('age').value;
    const lat = document.getElementById('lat').value;
    const lng = document.getElementById('lng').value;

    // Get selected injuries
    const injuryCheckboxes = document.querySelectorAll('.injury-grid input:checked');
    const injuries = Array.from(injuryCheckboxes).map(cb => cb.value);

    if (injuries.length === 0) {
        alert('최소 하나의 손상 부위를 선택하세요.');
        return;
    }

    const payload = { gcs_motor, sbp, rr, age, injuries, lat, lng };

    const resultEl = document.getElementById('result');
    resultEl.style.display = 'block';
    resultEl.innerHTML = '<p>병원 검색 중...</p>';

    try {
        const resp = await fetch('/api/recommend', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });

        if (!resp.ok) {
            const err = await resp.json();
            resultEl.innerHTML = `<p style='color:red;'>오류: ${err.error} (${err.detail || ''})</p>`;
            return;
        }

        const data = await resp.json();

        let html = `<small>CDC Triage 2021: ${data.field_triage.high_risk ? '고위험 외상' : '중등도 외상'}</small>`;
        data.matched.forEach((h, i) => {
            const rank = i === 0 ? '★' : `${i+1}`;
            let bedText = '정보 없음';
            if (h.status.hvec !== null && h.status.hvec !== undefined && h.status.hvec >= 0) {
                bedText = `${h.status.hvec}개`;
            }
            html += `<div class='result-item'><strong>${rank}순위: ${h.name}</strong><br>거리 ${h.dist_km.toFixed(1)}km / 등급: ${h.level} / 가용병상: ${bedText}<br><em>${h.reason}</em></div>`;
        });

        html += `<div class='disclaimer'>⚠️ 본 시스템은 의사결정 지원 도구입니다. 최종 이송 결정은 반드시 담당 구급대원이 합니다.</div>`;

        resultEl.innerHTML = html;
    } catch (e) {
        resultEl.innerHTML = `<p style='color:red;'>서버 연결 실패: ${e.message}</p>`;
    }
});

// Initialize GCS button (default to 6)
document.querySelector('button[data-value="6"]').classList.add('active');