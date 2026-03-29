// 입찰공고 포탈서비스 - 프론트엔드 JS
const API_BASE = '';  // same origin

let currentPage = 1;
let currentNotices = [];  // 모달용 데이터 저장

// ─── 초기 로드 ───────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    const user = await checkAuth();
    if (!user) return;

    loadSourceFilter();
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

// ─── 출처 필터 동적 로드 ────────────────────────
async function loadSourceFilter() {
    try {
        const res = await fetch(`${API_BASE}/api/sources`);
        if (!res.ok) return;
        const sources = await res.json();
        const select = document.getElementById('filter-source');
        // 기존 옵션 제거 (첫 번째 "전체 출처" 유지)
        while (select.options.length > 1) select.remove(1);
        sources.filter(s => s.is_active).forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.name;
            opt.textContent = s.name;
            select.appendChild(opt);
        });
    } catch (e) { console.error('출처 필터 로드 실패:', e); }
}

// ─── 통계 로드 ───────────────────────────────
async function loadStats() {
    try {
        const res = await fetch(`${API_BASE}/api/notices/stats`);
        const data = await res.json();

        const elTotal = document.getElementById('stat-total');
        if (!elTotal) return;
        elTotal.textContent = `전체: ${data.grand_total}건`;

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

        const titleHtml = escapeHtml(n.title);

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

// ─── 모달 ────────────────────────────────────
async function openModal(id) {
    // 모달 즉시 열기 (기본 정보)
    const n = currentNotices.find(n => n.id === id);
    if (!n) return;

    renderModal(n);
    document.getElementById('modal-overlay').classList.add('active');
    // 모달 스크롤을 맨 위로 리셋
    document.querySelector('.modal-content').scrollTop = 0;

    // 상세 API 호출 (확장 필드 보충)
    try {
        const res = await fetch(`${API_BASE}/api/notices/${id}`);
        const detail = await res.json();
        if (!detail.error) {
            renderModal(detail);
        }
    } catch (e) {
        console.error('상세 조회 실패:', e);
    }
}

let currentModalNoticeId = null;

function renderModal(n) {
    currentModalNoticeId = n.id;
    const statusText = n.status === 'ongoing' ? '진행중' : '마감';
    const keywords = (n.keywords || '').split(',').filter(k => k.trim())
        .map(k => `<span class="keyword-tag">${escapeHtml(k.trim())}</span>`).join(' ');

    // 태그 표시
    let tagHtml = '';
    if (n.tag) {
        const tagClass = getTagClass(n.tag);
        tagHtml = `<div class="modal-info"><label>태그</label> <span class="tag-badge ${tagClass}">${escapeHtml(n.tag)}</span>`;
        if (n.tagged_by_name) tagHtml += ` <span class="tag-meta">${escapeHtml(n.tagged_by_name)}</span>`;
        if (n.tag_memo) tagHtml += ` <span class="tag-meta">${escapeHtml(n.tag_memo)}</span>`;
        tagHtml += `</div>`;
    }

    // 태그 버튼 — 실무자: 검토요청만, 관리자(perm_bid_tag): 전체
    let tagButtons = '';
    if (currentUser) {
        const currentTag = n.tag || '';
        const isAdmin = hasPermission('bid_tag');
        let btns = '';
        // 검토요청: 모든 로그인 사용자
        btns += `<button class="tag-btn tag-btn-review ${currentTag === '검토요청' ? 'active' : ''}" onclick="setTag(${n.id}, '검토요청')">검토요청</button>`;
        // 입찰대상/제외: 관리자만
        if (isAdmin) {
            btns += `<button class="tag-btn tag-btn-bid ${currentTag === '입찰대상' ? 'active' : ''}" onclick="setTag(${n.id}, '입찰대상')">입찰대상</button>`;
            btns += `<button class="tag-btn tag-btn-exclude ${currentTag === '제외' ? 'active' : ''}" onclick="setTag(${n.id}, '제외')">제외</button>`;
        }
        if (currentTag) {
            btns += `<button class="tag-btn tag-btn-clear" onclick="removeTag(${n.id})">태그 해제</button>`;
        }
        tagButtons = `<div class="modal-tag-actions">${btns}</div>`;
    }

    // 확장 필드 (값이 있을 때만 표시)
    let extraFields = '';

    if (n.source === '나라장터') {
        // 나라장터 전용 상세 필드
        if (n.est_price) extraFields += `<div class="modal-info"><label>추정 가격</label> ${formatPrice(n.est_price)}원</div>`;
        if (n.assign_budget) extraFields += `<div class="modal-info"><label>배정 예산</label> ${formatPrice(n.assign_budget)}원</div>`;
        if (n.bid_method) extraFields += `<div class="modal-info"><label>입찰 방식</label> ${escapeHtml(n.bid_method)}</div>`;
        if (n.contract_method) extraFields += `<div class="modal-info"><label>계약 방법</label> ${escapeHtml(n.contract_method)}</div>`;
        if (n.award_method) extraFields += `<div class="modal-info"><label>낙찰 방식</label> ${escapeHtml(n.award_method)}</div>`;
        if (n.open_date) extraFields += `<div class="modal-info"><label>개찰 일시</label> ${escapeHtml(n.open_date)}</div>`;
        if (n.tech_eval_ratio || n.price_eval_ratio) {
            extraFields += `<div class="modal-info"><label>평가 비율</label> 기술 ${escapeHtml(n.tech_eval_ratio || '0')}% / 가격 ${escapeHtml(n.price_eval_ratio || '0')}%</div>`;
        }
        if (n.procure_class) extraFields += `<div class="modal-info"><label>조달 분류</label> ${escapeHtml(n.procure_class)}</div>`;
        if (n.contact_name || n.contact_phone) {
            let contactInfo = escapeHtml(n.contact_name || '');
            if (n.contact_phone) contactInfo += ` (${escapeHtml(n.contact_phone)})`;
            if (n.contact_email) contactInfo += ` ${escapeHtml(n.contact_email)}`;
            extraFields += `<div class="modal-info"><label>담당자</label> ${contactInfo}</div>`;
        }
    } else {
        // K-Startup / 중소벤처기업부 등 기존 필드
        if (n.biz_name) extraFields += `<div class="modal-info"><label>사업명</label> ${escapeHtml(n.biz_name)}</div>`;
        if (n.region) extraFields += `<div class="modal-info"><label>지원 지역</label> ${escapeHtml(n.region)}</div>`;
        if (n.target) extraFields += `<div class="modal-info"><label>지원 대상</label> ${escapeHtml(n.target)}</div>`;
        if (n.target_age) extraFields += `<div class="modal-info"><label>대상 연령</label> ${escapeHtml(n.target_age)}</div>`;
        if (n.biz_enyy) extraFields += `<div class="modal-info"><label>창업 연차</label> ${escapeHtml(n.biz_enyy)}</div>`;
        if (n.excl_target) extraFields += `<div class="modal-info"><label>제외 대상</label> ${escapeHtml(n.excl_target)}</div>`;
        if (n.budget) extraFields += `<div class="modal-info"><label>지원 규모</label> ${escapeHtml(n.budget)}</div>`;
        if (n.est_price) extraFields += `<div class="modal-info"><label>추정 가격</label> ${escapeHtml(n.est_price)}</div>`;
        if (n.apply_method) extraFields += `<div class="modal-info"><label>접수 방법</label> ${escapeHtml(n.apply_method)}</div>`;
        if (n.department) extraFields += `<div class="modal-info"><label>담당부서</label> ${escapeHtml(n.department)}</div>`;
        if (n.contact) extraFields += `<div class="modal-info"><label>문의처</label> ${escapeHtml(n.contact)}</div>`;
        if (n.content) extraFields += `<div class="modal-info modal-content-box"><label>사업 개요</label><div class="content-text">${escapeHtml(n.content)}</div></div>`;
    }

    // 링크 버튼들
    let links = '';
    if (n.url) links += `<a href="${escapeHtml(n.url)}" target="_blank" class="modal-link">공고 사이트 바로가기</a>`;
    if (n.apply_url) links += `<a href="${escapeHtml(n.apply_url)}" target="_blank" class="modal-link modal-link-apply">신청 페이지</a>`;

    // 첨부파일 (나라장터 attachments 또는 기존 file_url)
    let attachmentHtml = '';
    if (n.attachments) {
        try {
            const files = JSON.parse(n.attachments);
            if (files.length > 0) {
                attachmentHtml = '<div class="modal-attachments"><label>첨부파일</label><ul>';
                files.forEach(f => {
                    attachmentHtml += `<li><a href="${escapeHtml(f.url)}" target="_blank" class="attachment-link">${escapeHtml(f.name)}</a></li>`;
                });
                attachmentHtml += '</ul></div>';
            }
        } catch { /* ignore */ }
    }
    if (n.file_url && !attachmentHtml) {
        try {
            const files = JSON.parse(n.file_url);
            files.forEach(f => {
                links += `<a href="${escapeHtml(f.url)}" target="_blank" class="modal-link modal-link-file">${escapeHtml(f.name)}</a>`;
            });
        } catch {
            links += `<a href="${escapeHtml(n.file_url)}" target="_blank" class="modal-link modal-link-file">첨부파일 다운로드</a>`;
        }
    }

    document.getElementById('modal-body').innerHTML = `
        <div class="modal-title">${escapeHtml(n.title)}</div>
        ${tagButtons}
        ${tagHtml}
        <div class="modal-info"><label>출처</label> ${escapeHtml(n.source)}</div>
        <div class="modal-info"><label>기관</label> ${escapeHtml(n.organization || '-')}</div>
        <div class="modal-info"><label>분류</label> ${escapeHtml(n.category || '-')}</div>
        <div class="modal-info"><label>공고번호</label> ${escapeHtml(n.bid_no || '-')}</div>
        <div class="modal-info"><label>시작일</label> ${escapeHtml(n.start_date || '-')}</div>
        <div class="modal-info"><label>마감일</label> ${escapeHtml(n.end_date || '-')}</div>
        <div class="modal-info"><label>상태</label> <span class="badge badge-${n.status === 'ongoing' ? 'ongoing' : 'closed'}">${statusText}</span></div>
        <div class="modal-info"><label>키워드</label> ${keywords || '-'}</div>
        ${extraFields}
        ${attachmentHtml}
        <div class="modal-links">${links}</div>
    `;
}

// ─── 태그 관리 ────────────────────────────────
async function setTag(noticeId, tag) {
    try {
        const res = await fetch(`${API_BASE}/api/notice-tags/${noticeId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tag }),
        });
        const data = await res.json();
        if (data.success) {
            // 모달 새로고침
            const detailRes = await fetch(`${API_BASE}/api/notices/${noticeId}`);
            const detail = await detailRes.json();
            renderModal(detail);
            // 제외 태그 시 목록에서 사라지므로 리로드
            if (tag === '제외') loadNotices();
        }
    } catch (e) {
        console.error('태그 설정 실패:', e);
    }
}

async function removeTag(noticeId) {
    try {
        const res = await fetch(`${API_BASE}/api/notice-tags/${noticeId}`, { method: 'DELETE' });
        const data = await res.json();
        if (data.success) {
            const detailRes = await fetch(`${API_BASE}/api/notices/${noticeId}`);
            const detail = await detailRes.json();
            renderModal(detail);
            loadNotices();
        }
    } catch (e) {
        console.error('태그 해제 실패:', e);
    }
}

function getTagClass(tag) {
    const map = { '입찰대상': 'tag-bid', '제외': 'tag-exclude', '검토요청': 'tag-review', '낙찰': 'tag-won', '유찰': 'tag-lost' };
    return map[tag] || '';
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

function formatPrice(val) {
    if (!val) return '';
    const num = Number(val);
    if (isNaN(num)) return val;
    return num.toLocaleString('ko-KR');
}
