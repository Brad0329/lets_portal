/**
 * LETS 프로젝트 관리 시스템 — 공유 유틸리티
 * 모든 페이지에서 공통으로 사용되는 함수
 */

// ─── HTML 이스케이프 ────────────────────────────
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ─── 페이지네이션 범용 렌더러 ────────────────────
function renderPaginationGeneric(containerId, totalPages, current, goFnName) {
    const div = document.getElementById(containerId);
    if (totalPages <= 1) { div.innerHTML = ''; return; }

    let html = '';

    if (current > 1)
        html += `<button onclick="${goFnName}(${current - 1})">◀</button>`;

    const start = Math.max(1, current - 4);
    const end = Math.min(totalPages, current + 4);

    for (let i = start; i <= end; i++) {
        html += `<button class="${i === current ? 'active' : ''}" onclick="${goFnName}(${i})">${i}</button>`;
    }

    if (current < totalPages)
        html += `<button onclick="${goFnName}(${current + 1})">▶</button>`;

    div.innerHTML = html;
}

// ─── 출처 뱃지 클래스 ───────────────────────────
function getSourceClass(source) {
    if (source === 'K-Startup') return 'source-kstartup';
    if (source === '중소벤처기업부') return 'source-mss';
    if (source === '나라장터') return 'source-nara';
    return '';
}

// ─── 태그 뱃지 클래스 ───────────────────────────
function getTagClass(tag) {
    const map = { '입찰대상': 'tag-bid', '제외': 'tag-exclude', '검토요청': 'tag-review', '낙찰': 'tag-won', '유찰': 'tag-lost' };
    return map[tag] || '';
}

// ─── 상태 뱃지 HTML ─────────────────────────────
function statusBadgeHtml(status) {
    return status === 'ongoing'
        ? '<span class="badge badge-ongoing">진행중</span>'
        : '<span class="badge badge-closed">마감</span>';
}

// ─── 가격 포맷 ──────────────────────────────────
function formatPrice(val) {
    if (!val) return '';
    const num = Number(val);
    if (isNaN(num)) return val;
    return num.toLocaleString('ko-KR');
}

// ─── 첨부파일 파싱 ──────────────────────────────
function parseAttachments(notice) {
    if (!notice.attachments) return [];
    try {
        const arr = JSON.parse(notice.attachments);
        if (Array.isArray(arr)) return arr;
    } catch (e) {}
    return [];
}
