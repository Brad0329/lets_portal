// 설정 페이지 JS
const API_BASE = '';

document.addEventListener('DOMContentLoaded', async () => {
    const user = await checkAuth();
    if (!user) return;

    // 권한에 따라 섹션 표시
    if (hasPermission('display')) loadSettings();
    if (hasPermission('keyword')) loadKeywords();
    if (hasPermission('org')) loadOrganizations();
    loadInterestCategories();

    loadProfile();

    if (user.role === 'admin') {
        document.getElementById('user-mgmt-section').style.display = '';
        loadUsers();
    }
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

// ─── 나라장터 관심 중분류 ─────────────────────
async function loadInterestCategories() {
    try {
        const res = await fetch(`${API_BASE}/api/nara-categories`);
        if (!res.ok) return;
        const categories = await res.json();
        renderInterestCategories(categories);
    } catch (e) { console.error('관심 중분류 로드 실패:', e); }
}

function renderInterestCategories(categories) {
    const container = document.getElementById('interest-categories');
    if (!categories || categories.length === 0) {
        container.innerHTML = '<p style="color:#aaa;">등록된 관심 중분류가 없습니다.</p>';
        return;
    }

    // 대분류별 그룹핑
    const groups = {};
    categories.forEach(c => {
        if (!groups[c.large_class]) groups[c.large_class] = [];
        groups[c.large_class].push(c);
    });

    let html = '';
    for (const [lg, items] of Object.entries(groups)) {
        html += `<div style="margin-bottom:12px;">
            <div style="font-weight:600;font-size:13px;color:#1a5276;margin-bottom:4px;">${escapeHtml(lg)}</div>
            <div style="display:flex;flex-wrap:wrap;gap:6px;">`;
        items.forEach(c => {
            const active = c.is_active ? '' : 'opacity:0.4;text-decoration:line-through;';
            const bg = c.is_active ? '#d4efdf' : '#f2f3f4';
            const border = c.is_active ? '#27ae60' : '#bdc3c7';
            html += `<span onclick="toggleCategory(${c.id}, ${c.is_active ? 0 : 1})"
                style="cursor:pointer;padding:4px 10px;border-radius:12px;font-size:12px;background:${bg};border:1px solid ${border};${active}"
                title="클릭하여 ${c.is_active ? '비활성화' : '활성화'}">${escapeHtml(c.mid_class)}</span>`;
        });
        html += `</div></div>`;
    }
    container.innerHTML = html;
}

async function toggleCategory(id, newState) {
    try {
        await fetch(`${API_BASE}/api/nara-categories/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_active: newState }),
        });
        loadInterestCategories();
    } catch (e) { console.error('중분류 토글 실패:', e); }
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
        <p style="color:#e74c3c;font-weight:600;font-size:13px;margin-top:12px;">※ 기관목록 추가 삭제시 반드시 개발자와 협의 필요</p>
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

// ─── 계정 관리 (관리자 전용) ─────────────────

async function loadUsers() {
    try {
        const res = await fetch(`${API_BASE}/api/users`);
        if (!res.ok) return;
        const users = await res.json();
        renderUsers(users);
    } catch (e) {
        console.error('사용자 목록 로드 실패:', e);
    }
}

function renderUsers(users) {
    const container = document.getElementById('user-list');
    container.innerHTML = `
        <table class="org-table">
            <thead>
                <tr>
                    <th>ID</th>
                    <th>아이디</th>
                    <th>이름</th>
                    <th>역할</th>
                    <th>권한</th>
                    <th>생성일</th>
                    <th>관리</th>
                </tr>
            </thead>
            <tbody>
                ${users.map(u => {
                    const perms = [];
                    if (u.perm_display) perms.push('표시');
                    if (u.perm_keyword) perms.push('키워드');
                    if (u.perm_org) perms.push('기관');
                    const permStr = u.role === 'admin' ? '전체' : (perms.join(', ') || '-');
                    return `<tr>
                        <td>${u.id}</td>
                        <td>${escapeHtml(u.username)}</td>
                        <td>${escapeHtml(u.name)}</td>
                        <td>${u.role === 'admin' ? '관리자' : '실무자'}</td>
                        <td style="font-size:0.8rem">${permStr}</td>
                        <td style="font-size:0.8rem">${(u.created_at || '').slice(0, 10)}</td>
                        <td>
                            <button class="btn btn-sm" onclick="resetUserPw(${u.id})" style="font-size:0.75rem">PW초기화</button>
                            ${u.id !== currentUser.id ? `<button class="btn btn-sm btn-outline" onclick="deleteUser(${u.id}, '${escapeHtml(u.username)}')" style="font-size:0.75rem;color:#e74c3c;border-color:#e74c3c">삭제</button>` : ''}
                        </td>
                    </tr>`;
                }).join('')}
            </tbody>
        </table>
    `;
}

async function createUser() {
    const username = document.getElementById('new-user-id').value.trim();
    const name = document.getElementById('new-user-name').value.trim();
    const role = document.getElementById('new-user-role').value;
    const msg = document.getElementById('user-msg');

    if (!username || !name) { msg.textContent = '아이디와 이름을 입력하세요.'; msg.className = 'msg error'; return; }

    const body = {
        username, name, role,
        perm_bid_tag: document.getElementById('new-perm-bid-tag').checked ? 1 : 0,
        perm_display: document.getElementById('new-perm-display').checked ? 1 : 0,
        perm_keyword: document.getElementById('new-perm-keyword').checked ? 1 : 0,
        perm_org: document.getElementById('new-perm-org').checked ? 1 : 0,
    };

    try {
        const res = await fetch(`${API_BASE}/api/users`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await res.json();
        if (data.error) { msg.textContent = data.error; msg.className = 'msg error'; return; }
        msg.textContent = `계정 생성 완료! 초기 비밀번호: ${data.default_password}`;
        msg.className = 'msg';
        document.getElementById('new-user-id').value = '';
        document.getElementById('new-user-name').value = '';
        loadUsers();
    } catch (e) {
        msg.textContent = '생성 실패'; msg.className = 'msg error';
    }
}

async function resetUserPw(userId) {
    if (!confirm('비밀번호를 1234로 초기화하시겠습니까?')) return;
    try {
        const res = await fetch(`${API_BASE}/api/users/${userId}/reset-password`, { method: 'POST' });
        const data = await res.json();
        if (data.success) alert('비밀번호가 1234로 초기화되었습니다.');
    } catch (e) {
        alert('초기화 실패');
    }
}

async function deleteUser(userId, username) {
    if (!confirm(`"${username}" 계정을 삭제하시겠습니까?`)) return;
    try {
        await fetch(`${API_BASE}/api/users/${userId}`, { method: 'DELETE' });
        loadUsers();
    } catch (e) {
        alert('삭제 실패');
    }
}


// ─── 비밀번호 변경 ─────────────────────────────

async function changeMyPw() {
    const cur = document.getElementById('my-cur-pw').value;
    const newPw = document.getElementById('my-new-pw').value;
    const confirm = document.getElementById('my-confirm-pw').value;
    const msg = document.getElementById('pw-msg');

    if (!cur || !newPw) { msg.textContent = '모든 필드를 입력하세요.'; msg.className = 'msg error'; return; }
    if (newPw !== confirm) { msg.textContent = '새 비밀번호가 일치하지 않습니다.'; msg.className = 'msg error'; return; }

    try {
        const res = await fetch(`${API_BASE}/api/auth/change-password`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ current_password: cur, new_password: newPw }),
        });
        const data = await res.json();
        if (data.error) { msg.textContent = data.error; msg.className = 'msg error'; return; }
        msg.textContent = '비밀번호가 변경되었습니다.'; msg.className = 'msg';
        document.getElementById('my-cur-pw').value = '';
        document.getElementById('my-new-pw').value = '';
        document.getElementById('my-confirm-pw').value = '';
    } catch (e) {
        msg.textContent = '변경 실패'; msg.className = 'msg error';
    }
}

// ─── 회사 프로필 ─────────────────────────────

let profileData = [];

async function loadProfile() {
    try {
        const res = await fetch(`${API_BASE}/api/ai/profile`);
        if (!res.ok) return;
        const data = await res.json();
        profileData = data.categories || [];
        renderProfile();
    } catch (e) {
        console.error('프로필 로드 실패:', e);
    }
}

function renderProfile() {
    const container = document.getElementById('profile-container');
    if (!profileData.length) {
        container.innerHTML = '<p style="color:#aaa;">프로필 항목이 없습니다.</p>';
        return;
    }

    let html = '';
    for (const cat of profileData) {
        html += `<div class="profile-category">
            <h3 style="font-size:14px;color:#1a5276;margin:16px 0 8px;border-bottom:1px solid #eee;padding-bottom:4px">${escapeHtml(cat.category)}</h3>`;

        for (const f of cat.fields) {
            if (f.type === 'json') {
                html += renderJsonField(f);
            } else if (f.type === 'textarea') {
                html += `<div class="setting-item" style="margin-bottom:8px">
                    <label style="font-size:13px;color:#555">${escapeHtml(f.label)}</label>
                    <textarea data-key="${f.key}" style="width:100%;min-height:60px;padding:6px 8px;border:1px solid #d0d5dd;border-radius:6px;font-size:13px;resize:vertical">${escapeHtml(f.value || '')}</textarea>
                </div>`;
            } else if (f.type === 'boolean') {
                html += `<div class="setting-item" style="margin-bottom:8px">
                    <label style="font-size:13px;color:#555">${escapeHtml(f.label)}</label>
                    <select data-key="${f.key}" style="padding:6px 8px;border:1px solid #d0d5dd;border-radius:6px;font-size:13px">
                        <option value="true" ${f.value === 'true' ? 'selected' : ''}>예</option>
                        <option value="false" ${f.value === 'false' ? 'selected' : ''}>아니오</option>
                    </select>
                </div>`;
            } else {
                html += `<div class="setting-item" style="margin-bottom:8px">
                    <label style="font-size:13px;color:#555">${escapeHtml(f.label)}</label>
                    <input type="${f.type === 'number' ? 'number' : 'text'}" data-key="${f.key}" value="${escapeHtml(f.value || '')}"
                        style="width:100%;padding:6px 8px;border:1px solid #d0d5dd;border-radius:6px;font-size:13px" />
                </div>`;
            }
        }
        html += '</div>';
    }
    container.innerHTML = html;
}

function renderJsonField(field) {
    let items = [];
    try { items = JSON.parse(field.value || '[]'); } catch(e) { items = []; }

    const isProject = field.key === 'project_history';
    const isStaff = field.key === 'staff_list';

    let headers, fieldKeys;
    if (isProject) {
        headers = ['사업명', '발주처', '금액', '기간', '역할'];
        fieldKeys = ['name', 'client', 'amount', 'period', 'role'];
    } else if (isStaff) {
        headers = ['이름/직급', '자격증', '경력(년)', '전문분야'];
        fieldKeys = ['name', 'certification', 'experience', 'specialty'];
    } else {
        return `<div class="setting-item" style="margin-bottom:8px">
            <label style="font-size:13px;color:#555">${escapeHtml(field.label)}</label>
            <textarea data-key="${field.key}" style="width:100%;min-height:60px;padding:6px 8px;border:1px solid #d0d5dd;border-radius:6px;font-size:13px">${escapeHtml(field.value || '[]')}</textarea>
        </div>`;
    }

    let html = `<div style="margin-bottom:8px">
        <label style="font-size:13px;color:#555;font-weight:600">${escapeHtml(field.label)}</label>
        <table class="org-table" style="margin-top:4px;font-size:12px" id="json-table-${field.key}">
            <thead><tr>${headers.map(h => `<th>${h}</th>`).join('')}<th style="width:40px"></th></tr></thead>
            <tbody>`;

    items.forEach((item, idx) => {
        html += '<tr>';
        fieldKeys.forEach(fk => {
            html += `<td><input type="text" value="${escapeHtml(item[fk] || '')}" data-json-key="${field.key}" data-idx="${idx}" data-field="${fk}"
                style="width:100%;border:none;background:transparent;font-size:12px;padding:2px" /></td>`;
        });
        html += `<td><button onclick="removeJsonRow('${field.key}',${idx})" style="border:none;background:none;color:#e74c3c;cursor:pointer;font-size:14px" title="삭제">✕</button></td></tr>`;
    });

    html += `</tbody></table>
        <button onclick="addJsonRow('${field.key}')" class="btn btn-sm" style="margin-top:4px;font-size:11px">+ 추가</button>
    </div>`;
    return html;
}

function addJsonRow(key) {
    // 현재 테이블에서 값 수집 후 빈 행 추가
    const current = collectJsonData(key);
    const isProject = key === 'project_history';
    const newItem = isProject
        ? { name: '', client: '', amount: '', period: '', role: '' }
        : { name: '', certification: '', experience: '', specialty: '' };
    current.push(newItem);

    // profileData 업데이트 후 리렌더
    updateProfileField(key, JSON.stringify(current));
    renderProfile();
}

function removeJsonRow(key, idx) {
    const current = collectJsonData(key);
    current.splice(idx, 1);
    updateProfileField(key, JSON.stringify(current));
    renderProfile();
}

function collectJsonData(key) {
    const inputs = document.querySelectorAll(`[data-json-key="${key}"]`);
    const rows = {};
    inputs.forEach(inp => {
        const idx = parseInt(inp.dataset.idx);
        const field = inp.dataset.field;
        if (!rows[idx]) rows[idx] = {};
        rows[idx][field] = inp.value;
    });
    return Object.values(rows);
}

function updateProfileField(key, value) {
    for (const cat of profileData) {
        for (const f of cat.fields) {
            if (f.key === key) { f.value = value; return; }
        }
    }
}

async function saveProfile() {
    const msg = document.getElementById('profile-msg');
    const fields = [];

    // 일반 필드
    document.querySelectorAll('[data-key]').forEach(el => {
        fields.push({ key: el.dataset.key, value: el.value });
    });

    // JSON 필드 (테이블)
    const jsonKeys = new Set();
    document.querySelectorAll('[data-json-key]').forEach(el => jsonKeys.add(el.dataset.jsonKey));
    jsonKeys.forEach(key => {
        const data = collectJsonData(key);
        fields.push({ key, value: JSON.stringify(data) });
    });

    try {
        const res = await fetch(`${API_BASE}/api/ai/profile`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fields }),
        });
        const data = await res.json();
        if (data.success) {
            msg.textContent = `✅ 프로필 저장 완료! (${data.updated_count}건)`;
            msg.className = 'msg';
        } else {
            msg.textContent = '❌ 저장 실패';
            msg.className = 'msg error';
        }
        setTimeout(() => msg.textContent = '', 3000);
    } catch (e) {
        msg.textContent = '❌ 저장 실패: ' + e.message;
        msg.className = 'msg error';
    }
}

// ─── 유틸 (escapeHtml은 utils.js로 이동) ───
