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
    // 스크래퍼 날짜 기본값: 오늘 (로컬 시간 기준)
    const now = new Date();
    const today = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
    const sdEl = document.getElementById('scraper-start-date');
    const edEl = document.getElementById('scraper-end-date');
    if (sdEl) sdEl.value = today;
    if (edEl) edEl.value = today;
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

        const now = new Date();
        const today = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;

        return `
        <div class="source-card${inactive}" id="source-card-${s.id}">
            <div class="source-header">
                <span class="source-name">${escapeHtml(s.name)}</span>
                <span class="source-meta">마지막 수집: ${lastAt}</span>
            </div>
            <div class="source-stats">
                <div class="date-range-group">
                    <input type="date" id="start-date-${s.id}" value="${today}" class="date-input" />
                    <span class="date-sep">~</span>
                    <input type="date" id="end-date-${s.id}" value="${today}" class="date-input" />
                </div>
                <button class="btn-collect" id="btn-collect-${s.id}" onclick="collectSource(${s.id})"
                    ${s.is_active ? '' : 'disabled'}>수집</button>
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
        // 다건 결과 안내
        if (data.added_count !== undefined) {
            let msg = `${data.added_count}개 추가 완료`;
            if (data.skipped_count > 0) msg += `, ${data.skipped_count}개 중복 건너뜀 (${data.skipped.join(', ')})`;
            alert(msg);
        }
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

async function collectSource(sourceId) {
    const btn = document.getElementById(`btn-collect-${sourceId}`);
    const resultEl = document.getElementById(`result-${sourceId}`);
    const progressWrap = document.getElementById(`progress-wrap-${sourceId}`);
    const progressBar = document.getElementById(`progress-bar-${sourceId}`);
    const startDate = document.getElementById(`start-date-${sourceId}`).value;
    const endDate = document.getElementById(`end-date-${sourceId}`).value;

    btn.disabled = true;
    btn.textContent = '수집중...';
    btn.classList.add('collecting');
    resultEl.textContent = '';

    progressWrap.classList.add('active');
    progressBar.classList.add('indeterminate');

    try {
        const params = new URLSearchParams({ start_date: startDate, end_date: endDate });
        const resp = await fetch(`/api/sources/${sourceId}/collect?${params}`, { method: 'POST' });
        const data = await resp.json();

        progressBar.classList.remove('indeterminate');
        progressBar.style.width = '100%';

        if (resp.status === 409) {
            collectResults[sourceId] = { text: data.error || '이미 수집 중입니다.', color: '#e67e22' };
        } else if (data.error) {
            collectResults[sourceId] = { text: `오류: ${data.error}`, color: '#e74c3c' };
        } else {
            collectResults[sourceId] = {
                text: `${startDate}~${endDate} 수집 ${data.collected}건 (신규 ${data.inserted}, 업데이트 ${data.updated})`,
                color: '#27ae60'
            };
        }

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

let scraperFailedMap = {}; // { source_name: error_message }

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
        const cnt = s.last_collected_count != null ? s.last_collected_count : 0;
        const cntDisplay = cnt > 0 ? `${cnt}건` : '-';
        const siteUrl = s.site_url || '';
        // URL에서 도메인만 추출하여 표시
        let domainDisplay = '';
        if (siteUrl) {
            try {
                const u = new URL(siteUrl);
                domainDisplay = u.hostname.replace(/^www\./, '');
            } catch { domainDisplay = siteUrl; }
        }
        // 건수 클릭 시 공고 리스트로 이동 (해당 기관 필터)
        const cntLink = cnt > 0
            ? `<a class="scraper-item-cnt" href="/index.html?source=${encodeURIComponent(s.name)}" title="이 기관의 공고 보기">${cntDisplay}</a>`
            : `<span>${cntDisplay}</span>`;
        // 실패 상태 표시
        const failErr = scraperFailedMap[s.name];
        const failHtml = failErr
            ? `<span class="scraper-fail">수집실패</span> <button class="scraper-retry-btn" onclick="retryScraper('${escapeHtml(s.name)}', this)" title="${escapeHtml(failErr)}">재시도</button>`
            : '';
        return `<div class="scraper-item ${failErr ? 'scraper-item-failed' : ''}">
            <div class="scraper-item-left">
                <span class="scraper-item-name">${escapeHtml(s.name)}</span>
                ${siteUrl ? `<a class="scraper-item-url" href="${escapeHtml(siteUrl)}" target="_blank" title="${escapeHtml(siteUrl)}">${escapeHtml(domainDisplay)}</a>` : ''}
            </div>
            <span class="scraper-item-meta">${failHtml || (lastAt + ' / ' + cntLink)}</span>
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

let scraperTimerId = null;

async function collectAllScrapers() {
    const btn = document.getElementById('btn-scraper-collect');
    const resultEl = document.getElementById('scraper-result');
    const progressWrap = document.getElementById('scraper-progress-wrap');
    const progressBar = document.getElementById('scraper-progress-bar');
    const timerEl = document.getElementById('scraper-timer');
    const startDate = document.getElementById('scraper-start-date').value;
    const endDate = document.getElementById('scraper-end-date').value;

    btn.disabled = true;
    btn.textContent = '수집중...';
    btn.classList.add('collecting');
    resultEl.textContent = '';
    resultEl.style.color = '';

    progressWrap.classList.add('active');
    progressBar.classList.add('indeterminate');

    // 경과 시간 타이머 시작
    const startTime = Date.now();
    timerEl.style.display = 'inline';
    timerEl.textContent = '0초';
    scraperTimerId = setInterval(() => {
        const elapsed = Math.floor((Date.now() - startTime) / 1000);
        timerEl.textContent = `${elapsed}초`;
    }, 1000);

    // 기관 목록 자동 펼침 (수집 진행 상황 보이도록)
    const list = document.getElementById('scraper-list');
    const icon = document.getElementById('scraper-toggle-icon');
    if (list.style.display === 'none') {
        list.style.display = 'grid';
        icon.innerHTML = '&#9660;';
    }

    try {
        const params = new URLSearchParams({ target: 'scrapers', start_date: startDate, end_date: endDate });
        const resp = await fetch(`/api/collect?${params}`, { method: 'POST' });
        const data = await resp.json();

        // 중복 실행 감지 (409)
        if (resp.status === 409) {
            clearInterval(scraperTimerId);
            timerEl.style.display = 'none';
            resultEl.style.color = '#e67e22';
            resultEl.textContent = data.error || '이미 수집이 진행 중입니다.';
            progressBar.classList.remove('indeterminate');
            progressWrap.classList.remove('active');
            btn.disabled = false;
            btn.textContent = '일괄 수집';
            btn.classList.remove('collecting');
            return;
        }

        // 타이머 정지
        clearInterval(scraperTimerId);
        const totalSec = Math.floor((Date.now() - startTime) / 1000);
        timerEl.textContent = `${totalSec}초`;

        progressBar.classList.remove('indeterminate');
        progressBar.style.width = '100%';

        // 실패 기관 맵 갱신
        scraperFailedMap = {};
        if (data.results) {
            data.results.forEach(r => {
                if (r.error) scraperFailedMap[r.source] = r.error;
            });
        }

        if (data.error) {
            resultEl.style.color = '#e74c3c';
            resultEl.textContent = `오류: ${data.error}`;
        } else {
            resultEl.style.color = '#27ae60';
            const failMsg = data.failed > 0 ? `, 실패 ${data.failed}` : '';
            resultEl.textContent = `완료 — ${data.success}/${data.total}개 성공${failMsg} | 수집 ${data.collected}건, 매칭 ${data.matched}건, 신규 ${data.inserted}건 (${totalSec}초)`;
        }

        // 출처 목록 새로고침 → 각 기관별 수집 시간 갱신
        await loadSources();
        renderSources();
        renderScraperSection();

        // 완료 후에도 기관 목록 펼친 상태 유지
        const listAfter = document.getElementById('scraper-list');
        const iconAfter = document.getElementById('scraper-toggle-icon');
        listAfter.style.display = 'grid';
        iconAfter.innerHTML = '&#9660;';
    } catch (e) {
        clearInterval(scraperTimerId);
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
        }, 2000);
    }
}

// ─── 개별 스크래퍼 재시도 ──────────────────────────

async function retryScraper(sourceName, btnEl) {
    btnEl.disabled = true;
    btnEl.textContent = '수집중...';

    const startDate = document.getElementById('scraper-start-date').value;
    const endDate = document.getElementById('scraper-end-date').value;
    const params = new URLSearchParams({ start_date: startDate, end_date: endDate });

    try {
        const resp = await fetch(`/api/scraper/${encodeURIComponent(sourceName)}/collect?${params}`, { method: 'POST' });
        const data = await resp.json();

        if (data.error) {
            btnEl.textContent = '재시도';
            btnEl.disabled = false;
            alert(`${sourceName} 재수집 실패: ${data.error}`);
        } else {
            // 성공 → 실패 맵에서 제거 후 목록 갱신
            delete scraperFailedMap[sourceName];
            await loadSources();
            renderSources();
            renderScraperSection();
            // 기관 목록 펼친 상태 유지
            const list = document.getElementById('scraper-list');
            const icon = document.getElementById('scraper-toggle-icon');
            list.style.display = 'grid';
            icon.innerHTML = '&#9660;';
        }
    } catch (e) {
        btnEl.textContent = '재시도';
        btnEl.disabled = false;
        alert(`${sourceName} 재수집 실패: ${e.message}`);
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
