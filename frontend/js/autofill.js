// Phase C-5-B: 회사 프로필 자동 채우기
// 설정 > 회사 프로필 섹션 상단 카드 + 미리보기 모달.
// 업로드 → 기존 추출기 파이프라인 폴링 → 미리보기 → 선택 항목 반영 → 정량/역량 탭 리프레시.

(function () {
    const API = '/api/ai/extractor';

    let _srcId = null;          // 현재 분석 중/완료 src_id
    let _pollTimer = null;
    let _previewData = null;
    let _initialized = false;

    const CATEGORY_LABEL = {
        Identity: '정체성', Methodology: '방법론', USP: '차별화',
        Philosophy: '철학', Story: '스토리', Operational: '운영',
    };
    const CATEGORY_ORDER = ['Identity', 'Methodology', 'USP', 'Philosophy', 'Story', 'Operational'];

    function init() {
        if (_initialized) return;
        const form = document.getElementById('autofill-upload-form');
        if (!form) return;  // 설정 페이지 아님
        _initialized = true;
        form.addEventListener('submit', onSubmit);
        // 연도 기본값 = 현재 연도
        const y = document.getElementById('af-year');
        if (y && !y.value) y.value = new Date().getFullYear();
    }

    function setMsg(text, level) {
        const el = document.getElementById('autofill-msg');
        if (!el) return;
        el.textContent = text;
        el.className = 'msg ' + (level === 'error' ? 'error' : level === 'success' ? 'success' : '');
    }

    // -------- 업로드 --------
    async function onSubmit(e) {
        e.preventDefault();
        const fileInput = document.getElementById('af-file');
        if (!fileInput.files.length) {
            setMsg('파일을 선택하세요.', 'error');
            return;
        }
        const fd = new FormData();
        fd.append('file', fileInput.files[0]);
        fd.append('year', document.getElementById('af-year').value);
        fd.append('awarded', document.getElementById('af-awarded').value);
        fd.append('organization', document.getElementById('af-organization').value);
        fd.append('proposal_title', document.getElementById('af-title').value);

        setMsg('업로드 중...', '');
        try {
            const res = await fetch(`${API}/upload`, { method: 'POST', body: fd, credentials: 'include' });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || '업로드 실패');
            _srcId = data.src_id;
            setMsg('분석을 시작합니다...', '');
            renderProgress({ status: 'pending', progress: 0, processed_sections: 0, total_sections: 0, cost_krw: 0, current_section: '' });
            startPolling();
            // 역량 자산 탭도 새 소스를 인지하도록 한 번 트리거
            if (typeof window.initExtractor === 'function') {
                try { window.initExtractor(); } catch (_) {}
            }
        } catch (err) {
            setMsg('오류: ' + err.message, 'error');
        }
    }

    // -------- 진행률 폴링 --------
    function startPolling() {
        if (_pollTimer) clearTimeout(_pollTimer);
        _pollTimer = setTimeout(pollOnce, 500);
    }

    async function pollOnce() {
        if (!_srcId) return;
        try {
            const res = await fetch(`${API}/sources/${_srcId}`, { credentials: 'include' });
            if (!res.ok) throw new Error('조회 실패');
            const data = await res.json();
            const s = data.source || data;
            renderProgress(s);
            if (s.status === 'completed') {
                setMsg('분석 완료! 미리보기를 불러옵니다...', 'success');
                await openPreview(_srcId);
            } else if (s.status === 'failed') {
                setMsg('분석 실패: ' + (s.error_message || '알 수 없는 오류'), 'error');
            } else {
                _pollTimer = setTimeout(pollOnce, 3000);
            }
        } catch (e) {
            console.error('폴링 실패:', e);
            _pollTimer = setTimeout(pollOnce, 5000);
        }
    }

    function renderProgress(s) {
        const el = document.getElementById('autofill-progress');
        if (!el) return;
        el.style.display = '';
        const pct = Math.round((s.progress || 0) * 100);
        const statusText = s.status === 'pending' ? '대기 중'
            : s.status === 'processing' ? '분석 중'
            : s.status === 'completed' ? '완료'
            : s.status === 'failed' ? '실패' : s.status;
        el.innerHTML = `
            <div style="background:#e5e7eb;border-radius:4px;height:8px;overflow:hidden">
                <div style="background:#0ea5e9;height:100%;width:${pct}%;transition:width 0.3s"></div>
            </div>
            <div style="font-size:12px;color:#0c4a6e;margin-top:4px">
                ${statusText} · 섹션 ${s.processed_sections || 0}/${s.total_sections || '?'}
                ${s.current_section ? ` · ${escapeHtml(s.current_section)}` : ''}
                · 누적 ${Number(s.cost_krw || 0).toFixed(1)}원
            </div>
        `;
    }

    // -------- 미리보기 모달 --------
    async function openPreview(srcId) {
        try {
            const res = await fetch(`${API}/preview/${srcId}`, { credentials: 'include' });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || '미리보기 로드 실패');
            }
            _previewData = await res.json();
            renderModal();
            document.getElementById('autofill-modal').style.display = 'flex';
        } catch (e) {
            setMsg('미리보기 오류: ' + e.message, 'error');
        }
    }

    function renderModal() {
        if (!_previewData) return;
        const d = _previewData;
        const summary = `${d.source.file_name} · 정량 ${d.quantitative.project_history.length + d.quantitative.patents_certs.length}건 · claim ${d.source.claim_count}건`;
        document.getElementById('autofill-modal-summary').textContent = summary;

        const projects = d.quantitative.project_history;
        const certs = d.quantitative.patents_certs;
        const ignored = d.quantitative.ignored;
        const claimsByCat = d.claims.by_category;

        let html = '';

        // 정량 섹션 헤더
        html += `<h4 style="margin:0 0 8px;font-size:14px;color:#374151">📊 정량 정보 ${projects.length + certs.length}건</h4>`;

        // project_history
        html += renderQuantGroup(
            '📁 수행실적 (project_history)',
            projects.map(p => ({
                hint_id: p.hint_id,
                label: escapeHtml(p.name) + (p.client ? ` <span style="color:#6b7280">· ${escapeHtml(p.client)}</span>` : '') + (p.period ? ` <span style="color:#6b7280">· ${escapeHtml(p.period)}</span>` : ''),
                sub: p.section ? `출처: ${escapeHtml(p.section)}` : '',
                is_duplicate: p.is_duplicate,
                is_suspicious: p.is_suspicious,
            })),
            'proj'
        );

        // patents_certs
        html += renderQuantGroup(
            '🏅 인증·자격 (patents_certs)',
            certs.map(c => ({
                hint_id: c.hint_id,
                label: escapeHtml(c.text) + (c.year ? ` <span style="color:#6b7280">(${c.year})</span>` : '') + ` <span style="color:#9ca3af;font-size:11px">[${escapeHtml(c.type || '')}]</span>`,
                sub: c.section ? `출처: ${escapeHtml(c.section)}` : '',
                is_duplicate: c.is_duplicate,
                is_suspicious: c.is_suspicious,
            })),
            'cert'
        );

        // ignored (접힘)
        if (ignored.length) {
            html += `<details style="margin:8px 0 16px;background:#f9fafb;border:1px dashed #e5e7eb;border-radius:6px;padding:8px 12px">
                <summary style="cursor:pointer;font-size:12px;color:#6b7280">⚪ 매핑 없음 ${ignored.length}건 (프로필 스키마 밖 — 반영 안 됨)</summary>
                <div style="margin-top:6px;font-size:11px;color:#9ca3af">
                    ${ignored.map(i => `<div>· [${escapeHtml(i.type)}] ${escapeHtml(i.name)}</div>`).join('')}
                </div>
            </details>`;
        }

        // claims 섹션
        const totalClaims = d.source.claim_count;
        html += `<h4 style="margin:18px 0 8px;font-size:14px;color:#374151">💡 역량 claim ${totalClaims}건
            <span style="font-size:11px;font-weight:400;color:#6b7280">— 체크된 항목은 "승인" 처리됩니다</span>
        </h4>`;

        html += '<div style="display:flex;gap:6px;margin-bottom:8px">';
        html += `<button type="button" class="btn btn-sm" onclick="autofillToggleClaims(true, 0.9)">신뢰도 0.9+ 체크</button>`;
        html += `<button type="button" class="btn btn-sm" onclick="autofillToggleClaims(true, 0)">모두 체크</button>`;
        html += `<button type="button" class="btn btn-sm" style="background:#f3f4f6;color:#374151" onclick="autofillToggleClaims(false, 0)">모두 해제</button>`;
        html += '</div>';

        CATEGORY_ORDER.forEach(cat => {
            const items = claimsByCat[cat];
            if (!items || !items.length) return;
            html += renderClaimCategory(cat, items);
        });
        // 지정되지 않은 카테고리가 있다면 추가
        Object.keys(claimsByCat).forEach(cat => {
            if (CATEGORY_ORDER.includes(cat)) return;
            html += renderClaimCategory(cat, claimsByCat[cat]);
        });

        document.getElementById('autofill-modal-body').innerHTML = html;
    }

    function renderQuantGroup(title, items, prefix) {
        if (!items.length) {
            return `<div style="margin:4px 0 14px">
                <div style="font-size:13px;color:#374151;font-weight:600">${title}</div>
                <div style="font-size:12px;color:#9ca3af;padding:4px 0">해당 없음</div>
            </div>`;
        }
        const rows = items.map(it => {
            // 기본 체크: 중복·오탐 아닌 것
            const defaultChecked = !it.is_duplicate && !it.is_suspicious;
            const flags = [];
            if (it.is_duplicate) flags.push('<span style="background:#fee2e2;color:#991b1b;font-size:10px;padding:1px 5px;border-radius:8px">🔁 중복</span>');
            if (it.is_suspicious) flags.push('<span style="background:#fef3c7;color:#92400e;font-size:10px;padding:1px 5px;border-radius:8px">⚠ 오탐 의심</span>');
            return `<label style="display:flex;align-items:flex-start;gap:8px;padding:5px 4px;border-bottom:1px dotted #e5e7eb;font-size:12px;cursor:pointer">
                <input type="checkbox" data-kind="${prefix}" data-hint-id="${it.hint_id}" ${defaultChecked ? 'checked' : ''} style="margin-top:3px">
                <div style="flex:1;min-width:0">
                    <div style="line-height:1.5;word-break:break-all">${it.label} ${flags.join(' ')}</div>
                    ${it.sub ? `<div style="font-size:10px;color:#9ca3af;margin-top:1px">${it.sub}</div>` : ''}
                </div>
            </label>`;
        }).join('');
        return `<div style="margin:4px 0 14px">
            <div style="font-size:13px;color:#374151;font-weight:600;margin-bottom:4px">${title} <span style="color:#6b7280;font-weight:400">${items.length}건</span></div>
            <div style="border:1px solid #e5e7eb;border-radius:6px;padding:4px 8px">${rows}</div>
        </div>`;
    }

    function renderClaimCategory(cat, items) {
        const color = categoryColor(cat);
        const label = CATEGORY_LABEL[cat] || cat;
        const rows = items.map(c => {
            const defaultChecked = (c.confidence || 0) >= 0.9 && c.user_verified !== 2;
            const stmt = c.user_edited_statement || c.statement || '';
            const alreadyApproved = c.user_verified === 1;
            return `<label style="display:flex;align-items:flex-start;gap:8px;padding:5px 4px;border-bottom:1px dotted #e5e7eb;font-size:12px;cursor:pointer">
                <input type="checkbox" data-kind="claim" data-claim-id="${c.claim_id}" ${defaultChecked ? 'checked' : ''} ${alreadyApproved ? 'disabled' : ''} style="margin-top:3px">
                <div style="flex:1;min-width:0">
                    <div style="line-height:1.5">${escapeHtml(stmt)}</div>
                    <div style="font-size:10px;color:#9ca3af;margin-top:2px">
                        신뢰도 ${Number(c.confidence || 0).toFixed(2)}
                        ${alreadyApproved ? ' · <span style="color:#10b981">이미 승인됨</span>' : ''}
                    </div>
                </div>
            </label>`;
        }).join('');
        return `<details open style="margin-bottom:10px">
            <summary style="cursor:pointer;padding:4px 8px;background:${color.bg};color:${color.fg};border-radius:5px;font-size:12px;font-weight:600">
                ${label} <span style="font-weight:400">${items.length}건</span>
            </summary>
            <div style="border:1px solid #e5e7eb;border-top:none;border-radius:0 0 6px 6px;padding:4px 8px;margin-top:-2px">${rows}</div>
        </details>`;
    }

    function categoryColor(cat) {
        const colors = {
            Identity: { bg: '#fce7f3', fg: '#9f1239' },
            Methodology: { bg: '#dbeafe', fg: '#1e40af' },
            USP: { bg: '#fef3c7', fg: '#92400e' },
            Philosophy: { bg: '#e0e7ff', fg: '#3730a3' },
            Story: { bg: '#f3e8ff', fg: '#6b21a8' },
            Operational: { bg: '#ccfbf1', fg: '#0f766e' },
        };
        return colors[cat] || { bg: '#f3f4f6', fg: '#6b7280' };
    }

    // -------- 액션 --------
    // 기존 소스의 미리보기를 다시 열기 — 다른 곳(예: 역량 자산 탭)에서 호출 가능
    window.autofillOpenPreview = async function (srcId) {
        _srcId = srcId;
        await openPreview(srcId);
    };

    window.autofillCloseModal = function () {
        document.getElementById('autofill-modal').style.display = 'none';
    };

    window.autofillToggleClaims = function (check, minConf) {
        const boxes = document.querySelectorAll('#autofill-modal-body input[data-kind="claim"]');
        boxes.forEach(b => {
            if (b.disabled) return;
            if (check) {
                // 최소 신뢰도 필터: 체크박스 label에서 신뢰도 읽기
                const confText = b.closest('label').querySelector('div > div:last-child')?.textContent || '';
                const m = confText.match(/신뢰도\s*([0-9.]+)/);
                const conf = m ? parseFloat(m[1]) : 0;
                b.checked = conf >= minConf;
            } else {
                b.checked = false;
            }
        });
    };

    window.autofillApply = async function () {
        if (!_srcId) return;
        const hintIds = Array.from(document.querySelectorAll('#autofill-modal-body input[data-kind="proj"]:checked, #autofill-modal-body input[data-kind="cert"]:checked'))
            .map(b => parseInt(b.dataset.hintId, 10))
            .filter(Number.isFinite);
        const claimIds = Array.from(document.querySelectorAll('#autofill-modal-body input[data-kind="claim"]:checked'))
            .map(b => b.dataset.claimId);
        const mergeMode = (document.querySelector('input[name=af-merge-mode]:checked') || {}).value || 'fill_empty';

        const btn = document.getElementById('autofill-apply-btn');
        btn.disabled = true;
        btn.textContent = '반영 중...';
        try {
            const res = await fetch(`${API}/apply-to-profile`, {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    source_id: _srcId,
                    hint_ids: hintIds,
                    claim_ids: claimIds,
                    merge_mode: mergeMode,
                }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || '반영 실패');
            const pu = data.profile_updates || {};
            const msg = `✅ 반영 완료 — 수행실적 ${pu.project_history?.added || 0}건, 인증 ${pu.patents_certs?.lines_added || 0}줄, claim ${data.claims_approved || 0}건 승인`;
            setMsg(msg, 'success');
            autofillCloseModal();
            // 두 탭 리프레시
            if (typeof window.loadProfile === 'function') { try { window.loadProfile(); } catch (_) {} }
            if (typeof window.initExtractor === 'function') { try { window.initExtractor(); } catch (_) {} }
            // 업로드 폼 초기화
            document.getElementById('autofill-upload-form').reset();
            const y = document.getElementById('af-year');
            if (y) y.value = new Date().getFullYear();
        } catch (e) {
            setMsg('반영 오류: ' + e.message, 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = '선택한 항목 반영';
        }
    };

    // 배경 클릭으로 닫기 + ESC
    document.addEventListener('click', (e) => {
        const modal = document.getElementById('autofill-modal');
        if (modal && e.target === modal) autofillCloseModal();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const modal = document.getElementById('autofill-modal');
            if (modal && modal.style.display === 'flex') autofillCloseModal();
        }
    });

    // 초기화
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
