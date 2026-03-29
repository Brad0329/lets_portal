/**
 * 공고수집 출처 관리 페이지 (source-list.js)
 */

let allSources = [];
let commonKeywords = [];
let sourceKeywords = {}; // { sourceId: [keywords] }

document.addEventListener('DOMContentLoaded', async () => {
    const user = await checkAuth();
    if (!user) return;
    await loadAll();
});

async function loadAll() {
    await Promise.all([loadSources(), loadCommonKeywords()]);
    renderSources();
    renderScraperSection();
    renderCommonKeywords();
}

// ─── 출처 목록 ────────────────────────────────

async function loadSources() {
    try {
        const resp = await fetch('/api/sources');
        if (!resp.ok) throw new Error('출처 로드 실패');
        allSources = await resp.json();
        // 출처별 키워드 병렬 로드
        await Promise.all(allSources.map(async (s) => {
            try {
                const r = await fetch(`/api/sources/${s.id}/keywords`);
                if (r.ok) sourceKeywords[s.id] = await r.json();
                else sourceKeywords[s.id] = [];
            } catch { sourceKeywords[s.id] = []; }
        }));
    } catch (e) {
        console.error(e);
        allSources = [];
    }
}

function renderSources() {
    const container = document.getElementById('source-list');
    // scraper 타입은 별도 섹션에서 처리
    const apiSources = allSources.filter(s => s.collector_type !== 'scraper');
    if (!apiSources.length) {
        container.innerHTML = '<p style="color:#999">등록된 출처가 없습니다.</p>';
        return;
    }

    container.innerHTML = apiSources.map(s => {
        const inactive = s.is_active ? '' : ' inactive';
        const lastAt = s.last_collected_at ? formatDateTime(s.last_collected_at) : '수집 이력 없음';
        // 수집 결과 메시지가 있으면 우선 표시
        const cr = collectResults[s.id];
        const lastCnt = cr ? cr.text : (s.last_collected_count != null ? `${s.last_collected_count}건 수집됨` : '');
        const resultColor = cr ? `color:${cr.color}` : '';
        const kws = sourceKeywords[s.id] || [];

        return `
        <div class="source-card${inactive}" id="source-card-${s.id}">
            <div class="source-header">
                <span class="source-name">${escapeHtml(s.name)}</span>
                <span class="source-meta">마지막 수집: ${lastAt}</span>
            </div>
            <div class="source-stats">
                ${s.collector_type === 'nara' ? `
                <button class="btn-collect" id="btn-collect-${s.id}" onclick="collectSource(${s.id}, 'daily')"
                    ${s.is_active ? '' : 'disabled'}>빠른수집</button>
                <button class="btn-collect btn-collect-full" id="btn-full-${s.id}" onclick="collectSource(${s.id}, 'full')"
                    ${s.is_active ? '' : 'disabled'}>전체수집</button>
                ` : `
                <button class="btn-collect" id="btn-collect-${s.id}" onclick="collectSource(${s.id}, 'full')"
                    ${s.is_active ? '' : 'disabled'}>수집</button>
                `}
                <div class="progress-wrap" id="progress-wrap-${s.id}">
                    <div class="progress-bar" id="progress-bar-${s.id}"></div>
                </div>
                <span class="collect-result" id="result-${s.id}" style="${resultColor}">${lastCnt}</span>
            </div>
            <div class="kw-area">
                <div class="kw-area-label">추가 키워드:</div>
                <div class="kw-chips" id="source-kw-${s.id}">
                    ${kws.length ? kws.map(k => renderKwChip(k)).join('') : '<span style="color:#bbb;font-size:0.8rem">(없음)</span>'}
                    <div class="kw-add-inline">
                        <input type="text" id="source-kw-input-${s.id}" placeholder="키워드"
                            onkeydown="if(event.key==='Enter') addSourceKeyword(${s.id})" />
                        <button class="kw-add-btn" onclick="addSourceKeyword(${s.id})">+추가</button>
                    </div>
                </div>
            </div>
        </div>`;
    }).join('');
}

// ─── 공통 키워드 ──────────────────────────────

async function loadCommonKeywords() {
    try {
        const resp = await fetch('/api/keywords/common');
        if (!resp.ok) throw new Error('공통 키워드 로드 실패');
        commonKeywords = await resp.json();
    } catch (e) {
        console.error(e);
        commonKeywords = [];
    }
}

function renderCommonKeywords() {
    const container = document.getElementById('common-keywords');
    if (!commonKeywords.length) {
        container.innerHTML = '<span style="color:#bbb;font-size:0.8rem">등록된 공통 키워드가 없습니다.</span>';
        return;
    }
    container.innerHTML = commonKeywords.map(k => renderKwChip(k)).join('');
}

function renderKwChip(kw) {
    const cls = kw.is_active ? 'active' : 'inactive';
    return `<span class="kw-chip ${cls}" onclick="toggleKeyword(${kw.id})" title="클릭: ON/OFF 전환 | 우클릭: 삭제"
        oncontextmenu="event.preventDefault(); deleteKeyword(${kw.id}, '${escapeHtml(kw.keyword)}')"
        >${escapeHtml(kw.keyword)}<span class="kw-del" onclick="event.stopPropagation(); deleteKeyword(${kw.id}, '${escapeHtml(kw.keyword)}')">&times;</span></span>`;
}

// ─── 키워드 CRUD ──────────────────────────────

async function addCommonKeyword() {
    const input = document.getElementById('common-kw-input');
    const keyword = input.value.trim();
    if (!keyword) return;

    try {
        const resp = await fetch(`/api/keywords/common?keyword=${encodeURIComponent(keyword)}`, { method: 'POST' });
        const data = await resp.json();
        if (data.error) { alert(data.error); return; }
        input.value = '';
        await loadCommonKeywords();
        renderCommonKeywords();
    } catch (e) { alert('키워드 추가 실패: ' + e.message); }
}

async function addSourceKeyword(sourceId) {
    const input = document.getElementById(`source-kw-input-${sourceId}`);
    const keyword = input.value.trim();
    if (!keyword) return;

    try {
        const resp = await fetch(`/api/sources/${sourceId}/keywords?keyword=${encodeURIComponent(keyword)}`, { method: 'POST' });
        const data = await resp.json();
        if (data.error) { alert(data.error); return; }
        input.value = '';
        // 출처 키워드만 리로드
        const r = await fetch(`/api/sources/${sourceId}/keywords`);
        if (r.ok) sourceKeywords[sourceId] = await r.json();
        renderSources();
    } catch (e) { alert('키워드 추가 실패: ' + e.message); }
}

async function toggleKeyword(kwId) {
    try {
        await fetch(`/api/keywords/${kwId}/toggle`, { method: 'PUT' });
        await loadAll();
    } catch (e) { console.error(e); }
}

async function deleteKeyword(kwId, kwName) {
    if (!confirm(`'${kwName}' 키워드를 삭제하시겠습니까?`)) return;
    try {
        await fetch(`/api/keywords/${kwId}`, { method: 'DELETE' });
        await loadAll();
    } catch (e) { alert('삭제 실패: ' + e.message); }
}

// ─── 수집 실행 ────────────────────────────────

// 수집 완료 후 결과 메시지를 보존하기 위한 임시 저장
let collectResults = {}; // { sourceId: { text, color } }

async function collectSource(sourceId, mode = 'daily') {
    const btn = document.getElementById(`btn-collect-${sourceId}`);
    const btnFull = document.getElementById(`btn-full-${sourceId}`);
    const resultEl = document.getElementById(`result-${sourceId}`);
    const progressWrap = document.getElementById(`progress-wrap-${sourceId}`);
    const progressBar = document.getElementById(`progress-bar-${sourceId}`);

    btn.disabled = true;
    if (btnFull) btnFull.disabled = true;
    const activeBtn = (mode === 'full' && btnFull) ? btnFull : btn;
    activeBtn.textContent = '수집중...';
    activeBtn.classList.add('collecting');
    resultEl.textContent = '';

    // 진행바 표시 (indeterminate 애니메이션)
    progressWrap.classList.add('active');
    progressBar.classList.add('indeterminate');

    try {
        const resp = await fetch(`/api/sources/${sourceId}/collect?mode=${mode}`, { method: 'POST' });
        const data = await resp.json();

        // 진행바 완료 표시
        progressBar.classList.remove('indeterminate');
        progressBar.style.width = '100%';

        if (data.error) {
            collectResults[sourceId] = { text: `오류: ${data.error}`, color: '#e74c3c' };
        } else {
            collectResults[sourceId] = {
                text: `수집 ${data.collected}건 (신규 ${data.inserted}, 업데이트 ${data.updated})`,
                color: '#27ae60'
            };
        }

        // 잠시 100% 상태 보여주고 출처 목록 새로고침
        await new Promise(r => setTimeout(r, 600));
        await loadSources();
        renderSources();
    } catch (e) {
        collectResults[sourceId] = { text: '수집 실패: ' + e.message, color: '#e74c3c' };
        progressBar.classList.remove('indeterminate');
        progressWrap.classList.remove('active');
    }
}

// ─── 스크래퍼 섹션 ──────────────────────────────

function renderScraperSection() {
    const scrapers = allSources.filter(s => s.collector_type === 'scraper');
    const countEl = document.getElementById('scraper-count');
    const listEl = document.getElementById('scraper-list');
    const sectionEl = document.getElementById('scraper-section');

    if (!scrapers.length) {
        sectionEl.style.display = 'none';
        return;
    }
    sectionEl.style.display = '';
    countEl.textContent = `(${scrapers.length}개 기관)`;

    listEl.innerHTML = scrapers.map(s => {
        const lastAt = s.last_collected_at ? formatDateTime(s.last_collected_at) : '-';
        const cnt = s.last_collected_count != null ? `${s.last_collected_count}건` : '';
        return `<div class="scraper-item">
            <span class="scraper-item-name">${escapeHtml(s.name)}</span>
            <span class="scraper-item-meta">${lastAt} ${cnt}</span>
        </div>`;
    }).join('');
}

function toggleScraperList() {
    const list = document.getElementById('scraper-list');
    const icon = document.getElementById('scraper-toggle-icon');
    if (list.style.display === 'none') {
        list.style.display = 'grid';
        icon.innerHTML = '&#9660;';
    } else {
        list.style.display = 'none';
        icon.innerHTML = '&#9654;';
    }
}

async function collectAllScrapers() {
    const btn = document.getElementById('btn-scraper-collect');
    const resultEl = document.getElementById('scraper-result');
    const progressWrap = document.getElementById('scraper-progress-wrap');
    const progressBar = document.getElementById('scraper-progress-bar');

    btn.disabled = true;
    btn.textContent = '수집중...';
    btn.classList.add('collecting');
    resultEl.textContent = '';

    progressWrap.classList.add('active');
    progressBar.classList.add('indeterminate');

    try {
        const resp = await fetch('/api/collect?target=scrapers', { method: 'POST' });
        const data = await resp.json();

        progressBar.classList.remove('indeterminate');
        progressBar.style.width = '100%';

        if (data.error) {
            resultEl.style.color = '#e74c3c';
            resultEl.textContent = `오류: ${data.error}`;
        } else {
            resultEl.style.color = '#27ae60';
            resultEl.textContent = `성공 ${data.success}/${data.total}개 (수집 ${data.collected}건, 매칭 ${data.matched}건, 신규 ${data.inserted}건)`;
        }

        await new Promise(r => setTimeout(r, 800));
        await loadSources();
        renderSources();
        renderScraperSection();
    } catch (e) {
        resultEl.style.color = '#e74c3c';
        resultEl.textContent = '수집 실패: ' + e.message;
    } finally {
        btn.disabled = false;
        btn.textContent = '일괄 수집';
        btn.classList.remove('collecting');
        progressBar.classList.remove('indeterminate');
        setTimeout(() => {
            progressWrap.classList.remove('active');
            progressBar.style.width = '0%';
        }, 1000);
    }
}

// ─── 유틸 ─────────────────────────────────────

function formatDateTime(dt) {
    if (!dt) return '';
    try {
        // SQLite datetime: "2026-03-29 12:18:47" → ISO: "2026-03-29T12:18:47"
        const iso = dt.includes('T') ? dt : dt.replace(' ', 'T');
        const d = new Date(iso);
        if (isNaN(d.getTime())) return dt;
        const m = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        const h = String(d.getHours()).padStart(2, '0');
        const min = String(d.getMinutes()).padStart(2, '0');
        return `${m}/${day} ${h}:${min}`;
    } catch { return dt; }
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
