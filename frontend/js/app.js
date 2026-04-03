// 입찰공고 포탈서비스 - 프론트엔드 JS
const API_BASE = '';  // same origin

let currentPage = 1;
let currentNotices = [];  // 모달용 데이터 저장

// ─── 초기 로드 ───────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    const user = await checkAuth();
    if (!user) return;

    await loadSourceFilter();

    // URL 파라미터로 출처 필터 자동 설정 (?source=기관명)
    const urlParams = new URLSearchParams(window.location.search);
    const sourceParam = urlParams.get('source');
    if (sourceParam) {
        const select = document.getElementById('filter-source');
        // 옵션에 없으면 동적 추가 (scraper 출처는 목록에 있을 수 있음)
        let found = false;
        for (const opt of select.options) {
            if (opt.value === sourceParam) { found = true; break; }
        }
        if (!found) {
            const opt = document.createElement('option');
            opt.value = sourceParam;
            opt.textContent = sourceParam;
            select.appendChild(opt);
        }
        select.value = sourceParam;
    }

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
        // 실제 공고가 있는 출처만 가져오기
        const res = await fetch(`${API_BASE}/api/notices/sources`);
        if (!res.ok) return;
        const sources = await res.json();
        const select = document.getElementById('filter-source');
        // 기존 옵션 제거 (첫 번째 "전체 출처" 유지)
        while (select.options.length > 1) select.remove(1);
        sources.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.source;
            opt.textContent = `${s.source} (${s.count})`;
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

function searchByKeyword(keyword) {
    const input = document.getElementById('search-input');
    input.value = keyword;
    // 정렬: 입찰공고일 최신순 (기본값)
    document.getElementById('filter-sort').value = 'latest';
    currentPage = 1;
    loadNotices();
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
            .map(k => `<span class="keyword-tag" onclick="event.stopPropagation(); searchByKeyword('${escapeHtml(k.trim())}')" style="cursor:pointer;">${escapeHtml(k.trim())}</span>`)
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
    renderPaginationGeneric('pagination', totalPages, current, 'goPage');
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
        // 검토요청: 모든 로그인 사용자 — 사유 입력 UI 토글
        if (currentTag !== '검토요청') {
            btns += `<button class="tag-btn tag-btn-review" onclick="showReviewInput(${n.id})">검토요청</button>`;
        } else {
            btns += `<button class="tag-btn tag-btn-review active" disabled>검토요청</button>`;
        }
        // 입찰대상/제외: 모든 로그인 사용자
        btns += `<button class="tag-btn tag-btn-bid ${currentTag === '입찰대상' ? 'active' : ''}" onclick="setTag(${n.id}, '입찰대상')">입찰대상</button>`;
        btns += `<button class="tag-btn tag-btn-exclude ${currentTag === '제외' ? 'active' : ''}" onclick="setTag(${n.id}, '제외')">제외</button>`;
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
function showReviewInput(noticeId) {
    // 이미 입력창이 있으면 무시
    if (document.getElementById('review-input-area')) return;

    const tagActions = document.querySelector('.modal-tag-actions');
    if (!tagActions) return;

    const div = document.createElement('div');
    div.id = 'review-input-area';
    div.style.cssText = 'margin-top:10px;padding:10px;background:#fef9e7;border:1px solid #f9e79f;border-radius:6px;';
    div.innerHTML = `
        <label style="font-size:13px;font-weight:600;color:#7d6608;display:block;margin-bottom:6px;">검토요청 사유</label>
        <textarea id="review-memo-input" rows="15" style="width:100%;padding:8px;border:1px solid #d5d8dc;border-radius:4px;font-size:13px;resize:vertical;box-sizing:border-box;" placeholder="검토요청 사유를 입력하세요"></textarea>
        <div style="margin-top:8px;text-align:right;">
            <button onclick="document.getElementById('review-input-area').remove()" style="padding:6px 14px;border:1px solid #d5d8dc;background:#fff;border-radius:4px;cursor:pointer;margin-right:6px;">취소</button>
            <button onclick="submitReview(${noticeId})" style="padding:6px 14px;border:none;background:#2980b9;color:#fff;border-radius:4px;cursor:pointer;font-weight:600;">완료</button>
        </div>
    `;
    tagActions.parentNode.insertBefore(div, tagActions.nextSibling);
    document.getElementById('review-memo-input').focus();
}

async function submitReview(noticeId) {
    const memo = document.getElementById('review-memo-input').value.trim();
    if (!memo) {
        alert('검토요청 사유를 입력해주세요.');
        return;
    }
    await setTag(noticeId, '검토요청', memo);
}

async function setTag(noticeId, tag, memo = '') {
    try {
        const res = await fetch(`${API_BASE}/api/notice-tags/${noticeId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tag, memo }),
        });
        const data = await res.json();
        if (data.success) {
            // 모달 새로고침
            const detailRes = await fetch(`${API_BASE}/api/notices/${noticeId}`);
            const detail = await detailRes.json();
            renderModal(detail);
            // 첨부파일 백그라운드 수집 중이면 3초 후 자동 새로고침
            if (data.attachment_scraping) {
                _showAttachmentLoading();
                setTimeout(async () => {
                    const refreshRes = await fetch(`${API_BASE}/api/notices/${noticeId}`);
                    const refreshData = await refreshRes.json();
                    renderModal(refreshData);
                }, 3000);
            }
            // 제외 태그 시 목록에서 사라지므로 리로드
            if (tag === '제외') loadNotices();
        }
    } catch (e) {
        console.error('태그 설정 실패:', e);
    }
}

function _showAttachmentLoading() {
    const attachArea = document.querySelector('.modal-attachments');
    if (attachArea) {
        attachArea.innerHTML = '<label>첨부파일</label><p style="color:#888;font-size:13px;">📎 첨부파일 수집 중...</p>';
    } else {
        // 첨부파일 영역이 아직 없으면 모달 하단에 추가
        const modalBody = document.querySelector('.modal-body');
        if (modalBody) {
            const div = document.createElement('div');
            div.className = 'modal-attachments';
            div.innerHTML = '<label>첨부파일</label><p style="color:#888;font-size:13px;">📎 첨부파일 수집 중...</p>';
            // 태그 버튼 영역 앞에 삽입
            const tagActions = modalBody.querySelector('.modal-tag-actions');
            if (tagActions) {
                modalBody.insertBefore(div, tagActions);
            } else {
                modalBody.appendChild(div);
            }
        }
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

function closeModal() {
    document.getElementById('modal-overlay').classList.remove('active');
}

// ESC로 모달 닫기
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
});

// ─── 유틸 (escapeHtml, getSourceClass, getTagClass, formatPrice는 utils.js로 이동) ───
