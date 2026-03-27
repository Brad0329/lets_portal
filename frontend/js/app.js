// 입찰공고 포탈서비스 - 프론트엔드 JS
const API_BASE = '';  // same origin

let currentPage = 1;
let currentNotices = [];  // 모달용 데이터 저장

// ─── 초기 로드 ───────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    loadStats();
    loadNotices();

    // 엔터키 검색
    document.getElementById('search-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') loadNotices();
    });

    // 필터 변경 시 자동 검색
    ['filter-source', 'filter-status', 'filter-sort'].forEach(id => {
        document.getElementById(id).addEventListener('change', () => {
            currentPage = 1;
            loadNotices();
        });
    });
});

// ─── 통계 로드 ───────────────────────────────
async function loadStats() {
    try {
        const res = await fetch(`${API_BASE}/api/notices/stats`);
        const data = await res.json();

        document.getElementById('stat-total').textContent = `전체: ${data.grand_total}건`;

        const ongoing = data.by_source.reduce((sum, s) => sum + (s.ongoing || 0), 0);
        document.getElementById('stat-ongoing').textContent = `진행중: ${ongoing}건`;

        const lastUpdate = data.last_collected ? new Date(data.last_collected).toLocaleString('ko-KR') : '-';
        document.getElementById('stat-last-update').textContent = `마지막 수집: ${lastUpdate}`;
    } catch (e) {
        console.error('통계 로드 실패:', e);
    }
}

// ─── 공고 목록 로드 ──────────────────────────
async function loadNotices() {
    const q = document.getElementById('search-input').value;
    const source = document.getElementById('filter-source').value;
    const status = document.getElementById('filter-status').value;
    const sort = document.getElementById('filter-sort').value;

    const params = new URLSearchParams({
        q, source, status, sort,
        page: currentPage,
        size: 20,
    });

    const tbody = document.getElementById('notices-body');
    tbody.innerHTML = '<tr><td colspan="7" class="loading">검색 중...</td></tr>';

    try {
        const res = await fetch(`${API_BASE}/api/notices?${params}`);
        const data = await res.json();
        currentNotices = data.notices;
        renderNotices(data.notices);
        renderPagination(data.total_pages, data.page);
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="7" class="loading">데이터 로드 실패</td></tr>';
        console.error('공고 로드 실패:', e);
    }
}

// ─── 공고 렌더링 ─────────────────────────────
function renderNotices(notices) {
    const tbody = document.getElementById('notices-body');

    if (!notices || notices.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="loading">검색 결과가 없습니다.</td></tr>';
        return;
    }

    tbody.innerHTML = notices.map(n => {
        const sourceClass = getSourceClass(n.source);
        const statusBadge = n.status === 'ongoing'
            ? '<span class="badge badge-ongoing">진행중</span>'
            : '<span class="badge badge-closed">마감</span>';

        const titleHtml = n.url
            ? `<a href="${escapeHtml(n.url)}" target="_blank" class="notice-link">${escapeHtml(n.title)}</a>`
            : escapeHtml(n.title);

        const keywords = (n.keywords || '').split(',')
            .filter(k => k.trim())
            .map(k => `<span class="keyword-tag">${escapeHtml(k.trim())}</span>`)
            .join('');

        return `<tr onclick="openModal(${n.id})">
            <td><span class="source-badge ${sourceClass}">${escapeHtml(n.source)}</span></td>
            <td>${titleHtml}</td>
            <td>${escapeHtml(n.organization || '')}</td>
            <td>${escapeHtml(n.start_date || '-')}</td>
            <td>${escapeHtml(n.end_date || '-')}</td>
            <td>${statusBadge}</td>
            <td>${keywords}</td>
        </tr>`;
    }).join('');
}

// ─── 페이지네이션 ────────────────────────────
function renderPagination(totalPages, current) {
    const div = document.getElementById('pagination');
    if (totalPages <= 1) { div.innerHTML = ''; return; }

    let html = '';

    if (current > 1)
        html += `<button onclick="goPage(${current - 1})">◀</button>`;

    const start = Math.max(1, current - 4);
    const end = Math.min(totalPages, current + 4);

    for (let i = start; i <= end; i++) {
        html += `<button class="${i === current ? 'active' : ''}" onclick="goPage(${i})">${i}</button>`;
    }

    if (current < totalPages)
        html += `<button onclick="goPage(${current + 1})">▶</button>`;

    div.innerHTML = html;
}

function goPage(page) {
    currentPage = page;
    loadNotices();
    window.scrollTo(0, 0);
}

// ─── 수집 실행 ───────────────────────────────
async function runCollect() {
    const btn = document.getElementById('btn-collect');
    btn.textContent = '⏳ 수집중...';
    btn.classList.add('collecting');

    try {
        const res = await fetch(`${API_BASE}/api/collect`, { method: 'POST' });
        const data = await res.json();

        const summary = data.results.map(r =>
            `${r.source}: ${r.collected}건`
        ).join(', ');
        alert(`수집 완료!\n${summary}`);

        loadStats();
        loadNotices();
    } catch (e) {
        alert('수집 실패: ' + e.message);
    } finally {
        btn.textContent = '🔄 수집 실행';
        btn.classList.remove('collecting');
    }
}

// ─── 모달 ────────────────────────────────────
function openModal(id) {
    const n = currentNotices.find(n => n.id === id);
    if (!n) return;

    const statusText = n.status === 'ongoing' ? '진행중' : '마감';
    const keywords = (n.keywords || '').split(',').filter(k => k.trim())
        .map(k => `<span class="keyword-tag">${escapeHtml(k.trim())}</span>`).join(' ');

    document.getElementById('modal-body').innerHTML = `
        <div class="modal-title">${escapeHtml(n.title)}</div>
        <div class="modal-info"><label>출처</label> ${escapeHtml(n.source)}</div>
        <div class="modal-info"><label>기관</label> ${escapeHtml(n.organization || '-')}</div>
        <div class="modal-info"><label>분류</label> ${escapeHtml(n.category || '-')}</div>
        <div class="modal-info"><label>공고번호</label> ${escapeHtml(n.bid_no || '-')}</div>
        <div class="modal-info"><label>시작일</label> ${escapeHtml(n.start_date || '-')}</div>
        <div class="modal-info"><label>마감일</label> ${escapeHtml(n.end_date || '-')}</div>
        <div class="modal-info"><label>상태</label> <span class="badge badge-${n.status === 'ongoing' ? 'ongoing' : 'closed'}">${statusText}</span></div>
        <div class="modal-info"><label>키워드</label> ${keywords || '-'}</div>
        ${n.url ? `<a href="${escapeHtml(n.url)}" target="_blank" class="modal-link">🔗 공고 사이트 바로가기</a>` : ''}
    `;

    document.getElementById('modal-overlay').classList.add('active');
}

function closeModal() {
    document.getElementById('modal-overlay').classList.remove('active');
}

// ESC로 모달 닫기
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
});

// ─── 유틸 ────────────────────────────────────
function getSourceClass(source) {
    if (source === 'K-Startup') return 'source-kstartup';
    if (source === '중소벤처기업부') return 'source-mss';
    if (source === '나라장터') return 'source-nara';
    return '';
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
