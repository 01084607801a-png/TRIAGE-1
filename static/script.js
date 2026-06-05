// ═══════════════════════════════════════════
// TRIAGE-1 · 메인 스크립트 (PWA 모바일 최적화)
// ═══════════════════════════════════════════

// ── GCS Motor Score 선택 (행동 기준) ──────
document.querySelectorAll('.gcs-option').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.gcs-option').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const v = parseInt(btn.dataset.value, 10);
        document.getElementById('gcs_motor').value = v;
        // 6점 미만 → RED 경고 표시 (CDC 2021)
        document.getElementById('gcs-redwarn').style.display = (v < 6) ? 'flex' : 'none';
    });
});

// ── 65세 이상 토글 ────────────────────────
document.getElementById('age65').addEventListener('change', (e) => {
    document.getElementById('age').value = e.target.checked ? 70 : 45;
});

// ── 지도 초기화 ───────────────────────────
let map, marker;

function initMap() {
    map = L.map('map', { zoomControl: true }).setView([35.17, 126.92], 13);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap',
        maxZoom: 18,
    }).addTo(map);

    marker = L.marker([35.17, 126.92], { draggable: true }).addTo(map);
    marker.on('dragend', () => {
        const pos = marker.getLatLng();
        updateLocationInputs(pos.lat, pos.lng, true);
    });
    map.on('click', (e) => {
        updateLocationInputs(e.latlng.lat, e.latlng.lng, true);
    });
}

function updateLocationInputs(lat, lng, updateStatus = false) {
    document.getElementById('lat').value = lat.toFixed(6);
    document.getElementById('lng').value = lng.toFixed(6);
    marker.setLatLng([lat, lng]);
    map.setView([lat, lng], map.getZoom());
    if (updateStatus) {
        setLocationStatus(`📍 선택된 위치: ${lat.toFixed(4)}, ${lng.toFixed(4)}`);
    }
}

function setLocationStatus(msg) {
    document.getElementById('location-status').textContent = msg;
}

// ── GPS 위치 감지 ─────────────────────────
function getLocation() {
    if (!navigator.geolocation) {
        setLocationStatus('⚠️ GPS를 지원하지 않는 브라우저입니다');
        return;
    }
    setLocationStatus('📍 위치 감지 중...');
    navigator.geolocation.getCurrentPosition(
        (pos) => {
            const { latitude: lat, longitude: lng } = pos.coords;
            updateLocationInputs(lat, lng, false);
            setLocationStatus(`📍 위치 감지 완료 (${lat.toFixed(4)}, ${lng.toFixed(4)})`);
        },
        (err) => {
            setLocationStatus('⚠️ 위치 감지 실패 — 주소 검색 또는 지도를 사용하세요');
            console.warn('Geolocation error:', err);
        },
        { enableHighAccuracy: true, timeout: 10000 }
    );
}

// ── 주소 검색 ─────────────────────────────
async function searchAddress() {
    const query = document.getElementById('address').value.trim();
    if (!query) { setLocationStatus('⚠️ 검색어를 입력하세요'); return; }
    setLocationStatus('🔎 검색 중...');
    try {
        const resp = await fetch(`/api/geocode?q=${encodeURIComponent(query)}`);
        const data = await resp.json();
        const results = data.results || [];
        if (!results.length) { setLocationStatus('⚠️ 검색 결과가 없습니다'); return; }
        const { lat, lon, display_name } = results[0];
        updateLocationInputs(parseFloat(lat), parseFloat(lon), false);
        setLocationStatus(`📍 ${display_name}`);
    } catch (e) {
        setLocationStatus('⚠️ 검색 실패 — 네트워크를 확인하세요');
    }
}

// ── 권한이 이미 허용된 경우에만 자동 위치 감지 ──
// (로드 시 무조건 팝업을 띄우지 않음 = 모던 브라우저 권장 패턴)
function maybeAutoLocate() {
    const hint = "📍 '현재 위치 사용' 버튼을 눌러 위치를 설정하세요";
    if (navigator.permissions && navigator.permissions.query) {
        navigator.permissions.query({ name: 'geolocation' })
            .then((p) => {
                if (p.state === 'granted') getLocation();
                else setLocationStatus(hint);
            })
            .catch(() => setLocationStatus(hint));
    } else {
        setLocationStatus(hint);
    }
}

// ── 초기화 ────────────────────────────────
window.addEventListener('load', () => {
    initMap();
    maybeAutoLocate();
    document.getElementById('addressSearchBtn').addEventListener('click', searchAddress);
    document.getElementById('useCurrentLocationBtn').addEventListener('click', getLocation);
    document.getElementById('address').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); searchAddress(); }
    });
});

// ── 추천 요청 ─────────────────────────────
document.getElementById('recommendBtn').addEventListener('click', async () => {
    const injuries = Array.from(document.querySelectorAll('.injury-grid input:checked')).map(cb => cb.value);
    if (!injuries.length) { alert('손상 부위를 1개 이상 선택하세요.'); return; }

    const hr = document.getElementById('hr').value;
    const payload = {
        gcs_motor: document.getElementById('gcs_motor').value,
        sbp:       document.getElementById('sbp').value,
        rr:        document.getElementById('rr').value,
        age:       document.getElementById('age').value,
        mechanism: document.getElementById('mechanism').value,
        lat:       document.getElementById('lat').value,
        lng:       document.getElementById('lng').value,
        hr:        hr || null,
        injuries,
    };

    // 로딩 상태
    const btn = document.getElementById('recommendBtn');
    document.getElementById('btn-text').style.display = 'none';
    document.getElementById('btn-spinner').style.display = 'block';
    btn.disabled = true;

    const resultEl  = document.getElementById('result');
    const summaryEl = document.getElementById('patient-summary');
    resultEl.style.display = 'block';
    resultEl.innerHTML = '<p style="text-align:center;padding:24px;color:#64748b;">🔍 병원 검색 중...</p>';
    summaryEl.style.display = 'none';

    try {
        const resp = await fetch('/api/recommend', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            resultEl.innerHTML = `<p class="error-msg">❌ 오류: ${err.error || '알 수 없는 오류'}<br><small>${err.detail || ''}</small></p>`;
            return;
        }

        const data = await resp.json();
        renderResults(data, resultEl, summaryEl);
        setupChat(payload, data);   // 챗봇 컨텍스트 준비 + 표시

        // 결과로 스크롤
        setTimeout(() => summaryEl.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100);

    } catch (e) {
        resultEl.innerHTML = `<p class="error-msg">❌ 서버 연결 실패: ${e.message}</p>`;
    } finally {
        document.getElementById('btn-text').style.display = 'inline';
        document.getElementById('btn-spinner').style.display = 'none';
        btn.disabled = false;
    }
});

// ── 결과 렌더링 ───────────────────────────
function renderResults(data, resultEl, summaryEl) {
    const { patient, field_triage, matched, hems_eligibility, search_radius_km } = data;

    // 환자 요약
    const isRed = field_triage?.high_risk;
    const severityPct = Math.round((patient?.severity || 0) * 100);
    const ampt = patient?.ampt_score ?? '—';
    const rtcProb = (patient?.rtc_probability != null)
        ? `${Math.round(patient.rtc_probability * 100)}%`
        : '해당없음';

    summaryEl.style.display = 'block';
    summaryEl.innerHTML = `
        <h2>🩺 환자 상태 요약</h2>
        <div class="result-item">
            <span class="result-badge ${isRed ? 'badge-red' : 'badge-yellow'}">${isRed ? '🔴 RED' : '🟡 YELLOW'}</span>
            <span class="result-badge badge-blue">중증도 ${severityPct}%</span>
            <span class="result-badge badge-blue">AMPT ${ampt}/5</span>
            ${rtcProb !== '해당없음' ? `<span class="result-badge badge-blue">권역외상센터 확률 ${rtcProb}</span>` : ''}
        </div>
    `;

    // HEMS 권고
    let hemsHtml = '';
    if (hems_eligibility?.hems_recommended) {
        hemsHtml = `
            <div class="hems-alert">
                🚁 <strong>HEMS(닥터헬기) 이송 권고</strong><br>
                <small>${hems_eligibility.reason || ''}</small>
            </div>`;
    }

    // 병원 목록
    if (!matched?.length) {
        resultEl.innerHTML = hemsHtml + `
            <div class="result-item">
                <strong>추천 가능한 병원이 없습니다</strong><br>
                <small>반경 ${search_radius_km || 50}km 내 조건 만족 병원 없음.<br>손상 부위를 줄이거나 위치를 확인해 주세요.</small>
            </div>`;
        return;
    }

    let html = hemsHtml + `<p style="font-size:.82rem;color:var(--gray-600);margin-bottom:8px;">
        반경 ${search_radius_km || 50}km · ${matched.length}개 병원 추천</p>`;

    matched.forEach((h, i) => html += renderHospitalCard(h, i));
    resultEl.innerHTML = html;
}

// ── 개별 병원 카드 (요소형) ───────────────
function renderHospitalCard(h, i) {
    const rank = i === 0 ? '1순위 ★' : `${i + 1}순위`;
    const bed = h.bed_info || {};

    // ① 거리/시간
    const dist = (typeof h.route_distance_km === 'number' ? h.route_distance_km : h.dist_km) || 0;
    const timeTxt = h.travel_time_min ? `약 ${Math.round(h.travel_time_min)}분` : '도보·도로 추정';

    // ② 병상 — 응급실 가용 / 중환자실(외상ICU 우선)
    const er  = numOrNull(h.status?.hvec);
    const icu = numOrNull(bed.CRDT_ICU) ?? numOrNull(bed.hvicc);
    const erCell  = (er  != null) ? `${er}` : '–';
    const icuCell = (icu != null) ? `${icu}` : '–';
    const noBedData = (er == null && icu == null);

    // ③ 전문과 매칭
    const required = h.required_specialties || [];
    const missing = h.missing_specialties || [];
    const have = required.filter(s => !missing.includes(s));

    let specRow = '';
    if (required.length) {
        const haveTags = have.map(s => `<span class="spec-tag spec-have">✓ ${s}</span>`).join('');
        const missTags = missing.map(s => `<span class="spec-tag spec-miss">✕ ${s}</span>`).join('');
        specRow = `<div class="spec-row"><span>필요 전문과:</span>${haveTags}${missTags}</div>`;
    }

    // ④ HEMS
    const hemsPill = h.hems_recommended ? `<span class="hems-pill">🚁 HEMS 권고</span>` : '';

    // ⑤ 데이터 부재 안내
    const bedWarning = noBedData
        ? `<div class="bed-warning">⚠️ <span>실시간 병상 정보 조회 불가 — 기본 역량을 고려해 추천함. <strong>이송 전 유선 확인 필수</strong></span></div>`
        : '';

    // ⑥ AI(XAI) 설명
    const reason = (h.reason || '').replace(/</g,'&lt;').replace(/\n/g, '<br>');

    return `
    <div class="result-item">
        <div class="result-head">
            <span class="result-rank">${rank}</span>
            ${hemsPill}
        </div>
        <div class="result-name">${h.name}</div>
        <div style="margin:2px 0 4px;">
            <span class="result-badge badge-blue">${h.level}</span>
        </div>

        <div class="stat-grid">
            <div class="stat-cell">
                <div class="stat-icon">🚗</div>
                <div class="stat-val">${dist.toFixed(1)}<span style="font-size:.7rem;">km</span></div>
                <div class="stat-label">${timeTxt}</div>
            </div>
            <div class="stat-cell">
                <div class="stat-icon">🚨</div>
                <div class="stat-val ${er == null ? 'muted' : ''}">${erCell}</div>
                <div class="stat-label">응급실 병상</div>
            </div>
            <div class="stat-cell">
                <div class="stat-icon">🏥</div>
                <div class="stat-val ${icu == null ? 'muted' : ''}">${icuCell}</div>
                <div class="stat-label">중환자실</div>
            </div>
        </div>

        ${specRow}
        ${renderEquip(bed)}
        ${bedWarning}

        ${reason ? `<div class="xai-box"><div class="xai-label">AI 이송 판단 근거</div><div class="xai-text">${reason}</div></div>` : ''}
    </div>`;
}

function numOrNull(v) {
    return (v != null && v >= 0) ? Number(v) : null;
}

// 장비 가용 (CT / MRI / 인공호흡기) — 데이터 있을 때만 칩 표시
function renderEquip(bed) {
    const items = [];
    if (bed.CT_AVBL === true)   items.push('CT');
    if (bed.MRI_AVBL === true)  items.push('MRI');
    if (bed.VENT_AVBL === true) items.push('인공호흡기');
    if (!items.length) return '';
    return `<div class="equip-row">${items.map(x => `<span class="equip-tag">🟢 ${x}</span>`).join('')}</div>`;
}

// ═══════════════════════════════════════════
// AI 챗봇 — 추천 결과에 대한 질의응답 (Gemini)
// ═══════════════════════════════════════════
let chatContext = null;     // 현재 추천 컨텍스트
let chatHistory = [];       // 대화 기록

function setupChat(payload, data) {
    const r2 = v => (v == null ? null : Math.round(v * 100) / 100);
    const matched = (data.matched || []).slice(0, 5).map((h, i) => {
        const have = (h.required_specialties || []).filter(s => !(h.missing_specialties || []).includes(s));
        const su = h.suitability || {};
        return {
            rank: i + 1,
            name: h.name,
            level: h.level,
            dist_km: (typeof h.route_distance_km === 'number' ? h.route_distance_km : h.dist_km),
            time: h.travel_time_min || null,
            score: ((su.suitability_score ?? h.score ?? 0) * 100).toFixed(0),
            beds: (h.status?.hvec != null && h.status.hvec >= 0) ? h.status.hvec : '정보없음',
            spec: have.join(',') || '추론',
            miss: (h.missing_specialties || []).join(',') || '없음',
            reason: h.reason || '',
            // 세부 점수(0~1): 역량·거리·전문과·중환자실·실시간병상
            comp: {
                level: r2(su.hospital_level_score), dist: r2(su.distance_score),
                spec: r2(su.specialty_match_score), icu: r2(su.trauma_icu_score),
                realtime: r2(su.realtime_bed_score)
            }
        };
    });
    chatContext = {
        patient: {
            triage: data.field_triage?.high_risk ? 'RED(고위험)' : 'YELLOW(중등도)',
            gcs: payload.gcs_motor, sbp: payload.sbp, rr: payload.rr,
            age: payload.age, injuries: (payload.injuries || []).join(', '),
            severity: r2(data.matched?.[0]?.suitability?.patient_severity)
        },
        matched
    };
    chatHistory = [];
    document.getElementById('chat-log').innerHTML = '';
    document.getElementById('chatbox').style.display = 'block';
}

async function sendChat(question) {
    if (!question || !chatContext) return;
    const log = document.getElementById('chat-log');
    appendChat('user', question);
    const input = document.getElementById('chat-input');
    input.value = '';
    const thinking = appendChat('ai', '…생각 중');
    try {
        const resp = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question, context: { ...chatContext, history: chatHistory } })
        });
        const d = await resp.json();
        const answer = d.answer || d.error || '답변을 받지 못했습니다.';
        thinking.querySelector('.chat-bubble').textContent = answer;
        chatHistory.push({ role: 'user', text: question });
        chatHistory.push({ role: 'ai', text: answer });
    } catch (e) {
        thinking.querySelector('.chat-bubble').textContent = '⚠️ 연결 실패. 다시 시도해 주세요.';
    }
    log.scrollTop = log.scrollHeight;
}

function appendChat(role, text) {
    const log = document.getElementById('chat-log');
    const row = document.createElement('div');
    row.className = `chat-msg ${role}`;
    row.innerHTML = `<div class="chat-bubble">${text.replace(/</g, '&lt;')}</div>`;
    log.appendChild(row);
    log.scrollTop = log.scrollHeight;
    return row;
}

// 챗봇 이벤트 바인딩 (페이지 로드 시)
document.addEventListener('DOMContentLoaded', () => {
    const send = document.getElementById('chat-send');
    const input = document.getElementById('chat-input');
    if (send) send.addEventListener('click', () => sendChat(input.value.trim()));
    if (input) input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); sendChat(input.value.trim()); } });
    document.querySelectorAll('.chat-chip').forEach(c =>
        c.addEventListener('click', () => sendChat(c.dataset.q)));
});
