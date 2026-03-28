// 공통 인증/네비게이션 모듈
const AUTH_API = '';

let currentUser = null;

async function checkAuth() {
    try {
        const res = await fetch(`${AUTH_API}/api/auth/me`);
        const data = await res.json();
        if (!data.user) {
            location.href = '/login.html';
            return null;
        }
        if (data.user.must_change_pw && !location.pathname.includes('login')) {
            location.href = '/login.html';
            return null;
        }
        currentUser = data.user;
        renderNavbar();
        return data.user;
    } catch (e) {
        location.href = '/login.html';
        return null;
    }
}

function hasPermission(perm) {
    if (!currentUser) return false;
    if (currentUser.role === 'admin') return true;
    return !!currentUser['perm_' + perm];
}

async function doLogout() {
    await fetch(`${AUTH_API}/api/auth/logout`, { method: 'POST' });
    location.href = '/login.html';
}

function renderNavbar() {
    const nav = document.getElementById('main-navbar');
    if (!nav) return;

    const isAdmin = currentUser.role === 'admin';
    const page = location.pathname;

    const menuItems = [
        { href: '/dashboard.html', label: '대시보드', icon: '📊', show: true },
        { href: '/index.html', label: '공고 중인 사업', icon: '📋', show: true },
        { href: '/settings.html', label: '설정', icon: '⚙️', show: isAdmin || hasPermission('display') || hasPermission('keyword') || hasPermission('org') },
    ];

    const menuHtml = menuItems
        .filter(m => m.show)
        .map(m => {
            const active = page === m.href || (m.href === '/index.html' && page === '/');
            return `<a href="${m.href}" class="nav-link ${active ? 'active' : ''}">${m.icon} ${m.label}</a>`;
        }).join('');

    nav.innerHTML = `
        <div class="navbar-inner">
            <div class="navbar-brand">
                <a href="/dashboard.html" class="brand-link">LETS</a>
            </div>
            <div class="navbar-menu">${menuHtml}</div>
            <div class="navbar-user">
                <span class="user-info">${escapeHtmlNav(currentUser.name)} <span class="user-role">${currentUser.role === 'admin' ? '관리자' : '실무자'}</span></span>
                <button onclick="doLogout()" class="btn-logout">로그아웃</button>
            </div>
        </div>
    `;
}

function escapeHtmlNav(text) {
    if (!text) return '';
    const d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
}
