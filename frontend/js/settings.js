// 설정 페이지 JS
const API_BASE = '';

document.addEventListener('DOMContentLoaded', () => {
    loadSettings();
    loadKeywords();
    loadOrganizations();
});

// ─── 표시 설정 ───────────────────────────────
async function loadSettings() {
    try {
        const res = await fetch(`${API_BASE}/api/settings`);
        const data = await res.json();

        if (data.status_filter) document.getElementById('set-status-filter').value = data.status_filter.value;
        if (data.date_range_days) document.getElementById('set-date-range').value = data.date_range_days.value;
        if (data.sort_order) document.getElementById('set-sort-order').value = data.sort_order.value;
        if (data.items_per_page) document.getElementById('set-items-per-page').value = data.items_per_page.value;
    } catch (e) {
        console.error('설정 로드 실패:', e);
    }
}

async function saveSettings() {
    const settings = {
        status_filter: document.getElementById('set-status-filter').value,
        date_range_days: document.getElementById('set-date-range').value,
        sort_order: document.getElementById('set-sort-order').value,
        items_per_page: document.getElementById('set-items-per-page').value,
    };

    const msg = document.getElementById('settings-msg');
    try {
        for (const [key, value] of Object.entries(settings)) {
            await fetch(`${API_BASE}/api/settings/${key}?value=${encodeURIComponent(value)}`, { method: 'PUT' });
        }
        msg.textContent = '✅ 저장 완료!';
        msg.className = 'msg';
        setTimeout(() => msg.textContent = '', 3000);
    } catch (e) {
        msg.textContent = '❌ 저장 실패';
        msg.className = 'msg error';
    }
}

// ─── 키워드 관리 ─────────────────────────────
let allKeywords = [];

async function loadKeywords() {
    try {
        const res = await fetch(`${API_BASE}/api/keywords`);
        allKeywords = await res.json();
        renderKeywords();
    } catch (e) {
        console.error('키워드 로드 실패:', e);
    }
}

function renderKeywords() {
    const container = document.getElementById('keyword-groups');
    const activeCount = allKeywords.filter(k => k.is_active).length;
    document.getElementById('keyword-count').textContent = `활성 ${activeCount} / 전체 ${allKeywords.length}`;

    // 그룹별 분류
    const groups = {};
    allKeywords.forEach(kw => {
        const g = kw.keyword_group || '기타';
        if (!groups[g]) groups[g] = [];
        groups[g].push(kw);
    });

    // 그룹 셀렉트 업데이트
    const groupSelect = document.getElementById('new-keyword-group');
    const currentVal = groupSelect.value;
    const groupNames = Object.keys(groups);
    groupSelect.innerHTML = groupNames.map(g =>
        `<option value="${escapeHtml(g)}">${escapeHtml(g)}</option>`
    ).join('') + '<option value="사용자 추가">사용자 추가</option>';
    if (currentVal) groupSelect.value = currentVal;

    container.innerHTML = Object.entries(groups).map(([group, keywords]) => `
        <div class="keyword-group">
            <div class="keyword-group-title">${escapeHtml(group)}</div>
            <div class="keyword-chips">
                ${keywords.map(kw => `
                    <span class="keyword-chip ${kw.is_active ? 'active' : 'inactive'}"
                          data-id="${kw.id}"
                          onclick="toggleKeyword(${kw.id})"
                          oncontextmenu="deleteKeyword(event, ${kw.id}, '${escapeHtml(kw.keyword)}')">
                        ${escapeHtml(kw.keyword)}
                    </span>
                `).join('')}
            </div>
        </div>
    `).join('');
}

async function toggleKeyword(id) {
    try {
        const res = await fetch(`${API_BASE}/api/keywords/${id}/toggle`, { method: 'PUT' });
        const updated = await res.json();

        const idx = allKeywords.findIndex(k => k.id === id);
        if (idx >= 0) allKeywords[idx] = updated;
        renderKeywords();
    } catch (e) {
        console.error('키워드 토글 실패:', e);
    }
}

async function addKeyword() {
    const input = document.getElementById('new-keyword');
    const keyword = input.value.trim();
    if (!keyword) { input.focus(); return; }

    const group = document.getElementById('new-keyword-group').value;
    try {
        const res = await fetch(`${API_BASE}/api/keywords?keyword=${encodeURIComponent(keyword)}&keyword_group=${encodeURIComponent(group)}`, { method: 'POST' });
        const data = await res.json();
        if (data.error) {
            alert(data.error);
        } else {
            allKeywords.push(data);
            renderKeywords();
            input.value = '';
        }
    } catch (e) {
        alert('키워드 추가 실패: ' + e.message);
    }
}

async function deleteKeyword(event, id, name) {
    event.preventDefault();
    if (!confirm(`"${name}" 키워드를 삭제하시겠습니까?`)) return;

    try {
        await fetch(`${API_BASE}/api/keywords/${id}`, { method: 'DELETE' });
        allKeywords = allKeywords.filter(k => k.id !== id);
        renderKeywords();
    } catch (e) {
        alert('삭제 실패: ' + e.message);
    }
}

async function toggleAllKeywords(active) {
    const toToggle = allKeywords.filter(k => (active ? !k.is_active : k.is_active));
    for (const kw of toToggle) {
        await fetch(`${API_BASE}/api/keywords/${kw.id}/toggle`, { method: 'PUT' });
        kw.is_active = active ? 1 : 0;
    }
    renderKeywords();
}

// ─── 기관 목록 ───────────────────────────────
async function loadOrganizations() {
    try {
        const res = await fetch(`${API_BASE}/api/organizations`);
        const orgs = await res.json();
        renderOrganizations(orgs);
    } catch (e) {
        console.error('기관 로드 실패:', e);
    }
}

function renderOrganizations(orgs) {
    const container = document.getElementById('org-list');
    container.innerHTML = `
        <table class="org-table">
            <thead>
                <tr>
                    <th>#</th>
                    <th>기관명</th>
                    <th>분류</th>
                    <th>페이지</th>
                    <th>활성</th>
                </tr>
            </thead>
            <tbody>
                ${orgs.map((o, i) => `
                    <tr>
                        <td>${i + 1}</td>
                        <td>${o.url ? `<a href="${escapeHtml(o.url)}" target="_blank">${escapeHtml(o.name)}</a>` : escapeHtml(o.name)}</td>
                        <td>${escapeHtml(o.category || '')}</td>
                        <td>${escapeHtml(o.page_category || '')}</td>
                        <td class="${o.is_active ? 'org-active' : 'org-inactive'}">${o.is_active ? '●' : '○'}</td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
}

// ─── 수집 실행 ───────────────────────────────
async function runCollect() {
    const btn = document.getElementById('btn-collect');
    const msg = document.getElementById('collect-msg');
    btn.textContent = '⏳ 수집중...';
    btn.classList.add('collecting');
    msg.textContent = '';

    try {
        const res = await fetch(`${API_BASE}/api/collect`, { method: 'POST' });
        const data = await res.json();
        const summary = data.results.map(r => `${r.source}: ${r.collected}건`).join(', ');
        msg.textContent = `✅ 수집 완료! ${summary}`;
        msg.className = 'msg';
    } catch (e) {
        msg.textContent = '❌ 수집 실패: ' + e.message;
        msg.className = 'msg error';
    } finally {
        btn.textContent = '🔄 수집 실행';
        btn.classList.remove('collecting');
    }
}

// ─── 유틸 ────────────────────────────────────
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
