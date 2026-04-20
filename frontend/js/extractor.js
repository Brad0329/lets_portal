// Phase C-5: 역량 자산 추출기 UI
// 설정 페이지의 "역량 자산" 탭 내부 기능 — 업로드, 진행률, claim 검토/병합
(function () {
    const API = '/api/ai/extractor';
    const CATEGORIES = ['Identity', 'Methodology', 'USP', 'Philosophy', 'Story', 'Operational'];
    const CATEGORY_LABEL = {
        Identity: '정체성', Methodology: '방법론', USP: '차별화',
        Philosophy: '철학', Story: '스토리', Operational: '운영',
    };
    const VERIFIED_LABEL = { 0: '미검토', 1: '승인', 2: '숨김' };

    let _initialized = false;
    let _sourcesTimer = null;
    let _currentCategory = 'all';   // 'all' | CATEGORY
    let _currentVerified = 0;       // 0=pending, 1=approved, 2=hidden, -1=all
    let _claimsCache = { claims: [], counts: {} };
    let _editingClaimId = null;

    // -------- 초기화 --------
    window.initExtractor = function () {
        if (_initialized) { refreshAll(); return; }
        _initialized = true;

        document.getElementById('extractor-upload-form')
            .addEventListener('submit', onUploadSubmit);

        // 업로드 기본값 — 현재 연도
        const yearInput = document.getElementById('ex-year');
        if (!yearInput.value) yearInput.value = new Date().getFullYear();

        refreshAll();
    };

    function refreshAll() {
        loadSources();
        loadClaims();
    }

    // -------- 업로드 --------
    async function onUploadSubmit(e) {
        e.preventDefault();
        const msg = document.getElementById('ex-upload-msg');
        const fileInput = document.getElementById('ex-file');
        if (!fileInput.files.length) {
            setMsg(msg, '파일을 선택하세요.', 'error');
            return;
        }

        const fd = new FormData();
        fd.append('file', fileInput.files[0]);
        fd.append('year', document.getElementById('ex-year').value);
        fd.append('awarded', document.getElementById('ex-awarded').value);
        fd.append('organization', document.getElementById('ex-organization').value);
        fd.append('proposal_title', document.getElementById('ex-title').value);

        setMsg(msg, '업로드 중...', '');
        try {
            const res = await fetch(`${API}/upload`, { method: 'POST', body: fd });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || '업로드 실패');
            setMsg(msg, `✅ 업로드 완료 (${data.src_id}) — 백그라운드 추출 시작`, '');
            e.target.reset();
            document.getElementById('ex-year').value = new Date().getFullYear();
            loadSources();
        } catch (err) {
            setMsg(msg, `❌ ${err.message}`, 'error');
        }
    }

    // -------- 소스 목록 --------
    async function loadSources() {
        try {
            const res = await fetch(`${API}/sources`);
            if (!res.ok) return;
            const data = await res.json();
            renderSources(data.sources || []);
            scheduleSourcesPoll(data.sources || []);
        } catch (e) {
            console.error('sources 로드 실패:', e);
        }
    }

    function renderSources(sources) {
        const container = document.getElementById('extractor-sources');
        if (!sources.length) {
            container.innerHTML = '<p style="color:#aaa;font-size:13px">업로드된 제안서가 없습니다.</p>';
            return;
        }

        const html = sources.map(s => {
            const statusBadge = renderStatusBadge(s);
            const progressBar = s.status === 'processing'
                ? `<div style="background:#e5e7eb;border-radius:4px;height:8px;overflow:hidden;margin-top:6px">
                        <div style="background:#3b82f6;height:100%;width:${Math.round((s.progress || 0) * 100)}%"></div>
                   </div>
                   <div style="font-size:11px;color:#555;margin-top:4px">
                       ${escapeHtml(s.current_section || '')}
                       · 섹션 ${s.processed_sections}/${s.total_sections || '?'}
                       · 누적 ${Number(s.cost_krw || 0).toFixed(1)}원
                   </div>`
                : '';
            const errorInfo = s.status === 'failed' && s.error_message
                ? `<div style="color:#dc2626;font-size:12px;margin-top:4px">⚠ ${escapeHtml(s.error_message)}</div>`
                : '';
            const awardedLabel = s.awarded === 1 ? '✅ 수주' : (s.awarded === 0 ? '❌ 탈락' : '—');

            return `<div class="ex-source-card" style="border:1px solid #e5e7eb;border-radius:8px;padding:12px;margin-bottom:8px;background:#fff">
                <div style="display:flex;justify-content:space-between;align-items:start;gap:8px">
                    <div style="flex:1;min-width:0">
                        <div style="font-weight:600;font-size:13px">📄 ${escapeHtml(s.file_name)}</div>
                        <div style="font-size:12px;color:#555;margin-top:2px">
                            ${awardedLabel} · ${s.year || '?'}년 · ${escapeHtml(s.organization || '—')}
                            ${s.proposal_title ? ` · "${escapeHtml(s.proposal_title)}"` : ''}
                        </div>
                    </div>
                    <div style="display:flex;gap:4px;align-items:center">
                        ${statusBadge}
                        <button class="btn btn-sm" style="background:#fee2e2;color:#dc2626" onclick="extractorDeleteSource('${s.src_id}')">삭제</button>
                    </div>
                </div>
                ${progressBar}
                ${errorInfo}
                ${s.status === 'completed' ? renderCompletedInfo(s) : ''}
            </div>`;
        }).join('');

        container.innerHTML = html;
    }

    function renderStatusBadge(s) {
        const map = {
            pending: { text: '⏸ 대기', bg: '#fef3c7', fg: '#92400e' },
            processing: { text: '⏳ 처리중', bg: '#dbeafe', fg: '#1e40af' },
            completed: { text: '✅ 완료', bg: '#d1fae5', fg: '#065f46' },
            failed: { text: '❌ 실패', bg: '#fee2e2', fg: '#991b1b' },
        };
        const m = map[s.status] || map.pending;
        return `<span style="font-size:11px;padding:3px 8px;background:${m.bg};color:${m.fg};border-radius:4px;font-weight:600">${m.text}</span>`;
    }

    function renderCompletedInfo(s) {
        return `<div style="font-size:12px;color:#555;margin-top:6px;padding-top:6px;border-top:1px dashed #e5e7eb">
            claims: <strong>${s.claim_count}개</strong>
            · 섹션 ${s.processed_sections}개
            · ${Number(s.cost_krw || 0).toFixed(1)}원
            · tokens ${s.input_tokens}/${s.output_tokens}
        </div>`;
    }

    function scheduleSourcesPoll(sources) {
        if (_sourcesTimer) { clearTimeout(_sourcesTimer); _sourcesTimer = null; }
        const hasProcessing = sources.some(s => s.status === 'processing' || s.status === 'pending');
        if (hasProcessing) {
            _sourcesTimer = setTimeout(() => { loadSources(); loadClaims(); }, 3000);
        }
    }

    window.extractorDeleteSource = async function (src_id) {
        if (!confirm(`${src_id} 제안서와 추출된 claim을 모두 삭제합니다. 계속하시겠습니까?`)) return;
        try {
            const res = await fetch(`${API}/sources/${src_id}`, { method: 'DELETE' });
            if (!res.ok) throw new Error('삭제 실패');
            refreshAll();
        } catch (e) {
            alert('삭제 실패: ' + e.message);
        }
    };

    // -------- Claim 목록 --------
    async function loadClaims() {
        try {
            const params = new URLSearchParams();
            if (_currentCategory !== 'all') params.append('category', _currentCategory);
            if (_currentVerified >= 0) params.append('verified', String(_currentVerified));
            const res = await fetch(`${API}/claims?${params}`);
            if (!res.ok) return;
            _claimsCache = await res.json();
            renderClaims();
        } catch (e) {
            console.error('claims 로드 실패:', e);
        }
    }

    function renderClaims() {
        const section = document.getElementById('extractor-claims-section');
        const counts = _claimsCache.counts || {};
        const totalAll = Object.values(counts).reduce((s, c) => s + (c.total || 0), 0);

        if (totalAll === 0) {
            section.style.display = 'none';
            return;
        }
        section.style.display = '';

        renderToolbar(counts, totalAll);
        renderCategoryTabs(counts, totalAll);
        renderClaimCards(_claimsCache.claims || []);
    }

    function renderToolbar(counts, totalAll) {
        const pendingTotal = Object.values(counts).reduce((s, c) => s + (c.pending || 0), 0);
        const approvedTotal = Object.values(counts).reduce((s, c) => s + (c.approved || 0), 0);
        const hiddenTotal = Object.values(counts).reduce((s, c) => s + (c.hidden || 0), 0);

        const verifiedOptions = [
            { v: 0, label: `미검토 ${pendingTotal}`, color: '#f59e0b' },
            { v: 1, label: `승인 ${approvedTotal}`, color: '#10b981' },
            { v: 2, label: `숨김 ${hiddenTotal}`, color: '#6b7280' },
            { v: -1, label: `전체 ${totalAll}`, color: '#3b82f6' },
        ];
        const verifiedBtns = verifiedOptions.map(o => {
            const active = _currentVerified === o.v;
            return `<button type="button" onclick="extractorSwitchVerified(${o.v})"
                style="padding:4px 10px;border:1px solid ${o.color};background:${active ? o.color : 'transparent'};color:${active ? '#fff' : o.color};border-radius:14px;font-size:12px;cursor:pointer;font-weight:600">${o.label}</button>`;
        }).join('');

        const toolbar = document.getElementById('extractor-claims-toolbar');
        toolbar.innerHTML = `
            <div style="display:flex;gap:6px">${verifiedBtns}</div>
            <div style="flex:1"></div>
            <button type="button" class="btn btn-sm" onclick="extractorBulkApproveHighConf()">🤖 신뢰도 0.9+ 일괄 승인</button>
            <button type="button" class="btn btn-sm" onclick="extractorLoadMergeSuggestions()">🔁 병합 제안</button>
        `;
    }

    function renderCategoryTabs(counts, totalAll) {
        const tabs = document.getElementById('extractor-claims-tabs');
        const items = [{ key: 'all', label: `전체 ${totalAll}` }].concat(
            CATEGORIES.map(c => ({ key: c, label: `${CATEGORY_LABEL[c]} ${(counts[c] || {}).total || 0}` }))
        );
        tabs.innerHTML = items.map(it => {
            const active = _currentCategory === it.key;
            return `<button type="button" onclick="extractorSwitchCategory('${it.key}')"
                style="padding:6px 12px;border:none;background:none;border-bottom:2px solid ${active ? '#2980b9' : 'transparent'};margin-bottom:-1px;font-size:12px;color:${active ? '#2980b9' : '#555'};font-weight:${active ? '600' : '400'};cursor:pointer">${it.label}</button>`;
        }).join('');
    }

    function renderClaimCards(claims) {
        const list = document.getElementById('extractor-claims-list');
        if (!claims.length) {
            list.innerHTML = '<p style="color:#aaa;font-size:13px;padding:16px">해당 조건에 맞는 claim이 없습니다.</p>';
            return;
        }
        list.innerHTML = claims.map(renderClaimCard).join('');
    }

    function renderClaimCard(c) {
        const isEditing = _editingClaimId === c.claim_id;
        const statement = c.statement || '';
        const tagsHtml = renderTags(c.tags);
        const sectionsHtml = (c.proposal_sections || []).map(s =>
            `<span style="font-size:11px;background:#eef2ff;color:#3730a3;padding:1px 6px;border-radius:3px;margin-right:3px">${escapeHtml(s)}</span>`
        ).join('');
        const variantsHtml = renderVariants(c.length_variants);
        const categoryColor = categoryColor_(c.category);
        const verifiedBadge = renderVerifiedBadge(c.user_verified);
        const recurBadge = c.recurrence > 1
            ? `<span style="font-size:11px;color:#7c3aed;margin-left:4px">×${c.recurrence}</span>` : '';

        const statementBlock = isEditing
            ? `<textarea id="edit-stmt-${c.claim_id}" style="width:100%;min-height:60px;padding:6px 8px;border:1px solid #93c5fd;border-radius:6px;font-size:13px">${escapeHtml(statement)}</textarea>
               <div style="margin-top:4px;display:flex;gap:4px">
                   <button class="btn btn-sm" onclick="extractorSaveEdit('${c.claim_id}')">💾 저장</button>
                   <button class="btn btn-sm" style="background:#f3f4f6;color:#555" onclick="extractorCancelEdit()">취소</button>
               </div>`
            : `<div style="font-size:13px;line-height:1.5">${escapeHtml(statement)}</div>`;

        return `<div style="border:1px solid #e5e7eb;border-radius:8px;padding:12px;margin-bottom:8px;background:#fff">
            <div style="display:flex;justify-content:space-between;align-items:start;gap:8px;margin-bottom:6px">
                <div style="display:flex;gap:4px;align-items:center;flex-wrap:wrap">
                    <span style="font-size:11px;padding:2px 8px;background:${categoryColor.bg};color:${categoryColor.fg};border-radius:4px;font-weight:600">${CATEGORY_LABEL[c.category] || c.category}</span>
                    ${verifiedBadge}
                    ${recurBadge}
                    <span style="font-size:11px;color:#888">신뢰도 ${Number(c.confidence || 0).toFixed(2)}</span>
                </div>
                <div style="display:flex;gap:4px">
                    ${c.user_verified !== 1 ? `<button class="btn btn-sm" style="background:#d1fae5;color:#065f46" onclick="extractorSetVerified('${c.claim_id}',1)">승인</button>` : ''}
                    ${c.user_verified !== 2 ? `<button class="btn btn-sm" style="background:#f3f4f6;color:#374151" onclick="extractorSetVerified('${c.claim_id}',2)">숨김</button>` : ''}
                    ${c.user_verified !== 0 ? `<button class="btn btn-sm" style="background:#fef3c7;color:#92400e" onclick="extractorSetVerified('${c.claim_id}',0)">미검토로</button>` : ''}
                    ${!isEditing ? `<button class="btn btn-sm" onclick="extractorStartEdit('${c.claim_id}')">✎ 편집</button>` : ''}
                </div>
            </div>
            ${statementBlock}
            ${tagsHtml ? `<div style="margin-top:6px">${tagsHtml}</div>` : ''}
            ${sectionsHtml ? `<div style="margin-top:4px">섹션: ${sectionsHtml}</div>` : ''}
            ${variantsHtml}
            <div style="font-size:11px;color:#888;margin-top:6px;border-top:1px dashed #eee;padding-top:4px">
                📄 ${escapeHtml(c.source_section || '—')} · ${c.claim_id}
                ${c.merged_from && c.merged_from.length ? ` · 🔁 병합 ${c.merged_from.length}건` : ''}
            </div>
        </div>`;
    }

    function renderTags(tags) {
        if (!tags) return '';
        const allTags = [].concat(tags.domain || [], tags.audience || [], tags.method || []);
        if (!allTags.length) return '';
        return allTags.map(t =>
            `<span style="font-size:11px;background:#f0f9ff;color:#075985;padding:1px 6px;border-radius:10px;margin-right:3px">#${escapeHtml(t)}</span>`
        ).join('');
    }

    function renderVariants(v) {
        if (!v || Object.keys(v).length === 0) return '';
        const parts = [];
        if (v.tagline) parts.push(`<div style="font-size:11px;color:#666"><strong>태그라인:</strong> ${escapeHtml(v.tagline)}</div>`);
        if (v.summary) parts.push(`<div style="font-size:11px;color:#666"><strong>요약:</strong> ${escapeHtml(v.summary)}</div>`);
        return parts.length ? `<div style="margin-top:6px;padding:6px 8px;background:#f9fafb;border-left:3px solid #d1d5db;border-radius:2px">${parts.join('')}</div>` : '';
    }

    function renderVerifiedBadge(v) {
        const map = {
            0: { text: '미검토', bg: '#fef3c7', fg: '#92400e' },
            1: { text: '승인', bg: '#d1fae5', fg: '#065f46' },
            2: { text: '숨김', bg: '#f3f4f6', fg: '#6b7280' },
        };
        const m = map[v] || map[0];
        return `<span style="font-size:11px;padding:2px 6px;background:${m.bg};color:${m.fg};border-radius:3px">${m.text}</span>`;
    }

    function categoryColor_(cat) {
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

    // -------- Claim 액션 --------
    window.extractorSwitchCategory = function (cat) {
        _currentCategory = cat;
        loadClaims();
    };
    window.extractorSwitchVerified = function (v) {
        _currentVerified = v;
        loadClaims();
    };
    window.extractorStartEdit = function (claim_id) {
        _editingClaimId = claim_id;
        renderClaims();
    };
    window.extractorCancelEdit = function () {
        _editingClaimId = null;
        renderClaims();
    };
    window.extractorSaveEdit = async function (claim_id) {
        const ta = document.getElementById(`edit-stmt-${claim_id}`);
        const statement = (ta ? ta.value : '').trim();
        if (!statement) { alert('statement는 비울 수 없습니다.'); return; }
        try {
            const res = await fetch(`${API}/claims/${claim_id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ statement }),
            });
            if (!res.ok) throw new Error('저장 실패');
            _editingClaimId = null;
            loadClaims();
        } catch (e) { alert(e.message); }
    };
    window.extractorSetVerified = async function (claim_id, v) {
        try {
            const res = await fetch(`${API}/claims/${claim_id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_verified: v }),
            });
            if (!res.ok) throw new Error('상태 변경 실패');
            loadClaims();
        } catch (e) { alert(e.message); }
    };

    window.extractorBulkApproveHighConf = async function () {
        if (!confirm('신뢰도 0.9 이상 미검토 claim을 모두 승인합니다. 계속하시겠습니까?')) return;
        try {
            const res = await fetch(`${API}/claims/bulk-verify`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    filter: { min_confidence: 0.9 },
                    user_verified: 1,
                }),
            });
            const data = await res.json();
            alert(`${data.updated || 0}건 승인 완료`);
            loadClaims();
        } catch (e) { alert('일괄 승인 실패: ' + e.message); }
    };

    // -------- 병합 제안 --------
    window.extractorLoadMergeSuggestions = async function () {
        const panel = document.getElementById('extractor-merge-panel');
        panel.style.display = '';
        panel.innerHTML = '<p style="color:#888;font-size:13px">병합 후보 계산 중...</p>';
        try {
            const params = new URLSearchParams();
            if (_currentCategory !== 'all') params.append('category', _currentCategory);
            const res = await fetch(`${API}/claims/merge-suggestions?${params}`);
            const data = await res.json();
            renderMergePanel(data.suggestions || [], data.threshold);
        } catch (e) {
            panel.innerHTML = `<p style="color:#dc2626">병합 제안 실패: ${escapeHtml(e.message)}</p>`;
        }
    };

    function renderMergePanel(suggestions, threshold) {
        const panel = document.getElementById('extractor-merge-panel');
        const header = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <strong style="font-size:13px">🔁 병합 제안 (유사도 ≥ ${threshold}, 미검토 대상)</strong>
            <button class="btn btn-sm" style="background:#f3f4f6;color:#555" onclick="extractorCloseMergePanel()">닫기</button>
        </div>`;
        if (!suggestions.length) {
            panel.innerHTML = header + '<p style="color:#666;font-size:13px">병합 후보가 없습니다.</p>';
            return;
        }
        const body = suggestions.map((s, i) => {
            const primary = s.claim_a.confidence >= s.claim_b.confidence ? s.claim_a : s.claim_b;
            const other = primary === s.claim_a ? s.claim_b : s.claim_a;
            return `<div style="border:1px solid #fed7aa;border-radius:6px;padding:8px;margin-bottom:6px;background:#fff">
                <div style="font-size:11px;color:#9a3412;margin-bottom:4px">
                    ${CATEGORY_LABEL[s.category] || s.category} · 유사도 ${s.similarity}
                </div>
                <div style="font-size:12px;line-height:1.5">
                    <div><span style="color:#059669">● 주:</span> ${escapeHtml(primary.statement)} <span style="color:#888">(${primary.confidence.toFixed(2)})</span></div>
                    <div><span style="color:#6b7280">● 병합:</span> ${escapeHtml(other.statement)} <span style="color:#888">(${other.confidence.toFixed(2)})</span></div>
                </div>
                <div style="margin-top:6px;display:flex;gap:4px">
                    <button class="btn btn-sm" onclick="extractorExecuteMerge('${primary.claim_id}','${other.claim_id}')">🔁 병합</button>
                    <button class="btn btn-sm" style="background:#f3f4f6;color:#555" onclick="extractorDismissSuggestion(${i})">건너뛰기</button>
                </div>
            </div>`;
        }).join('');
        panel.innerHTML = header + body;
    }

    window.extractorCloseMergePanel = function () {
        document.getElementById('extractor-merge-panel').style.display = 'none';
    };
    window.extractorDismissSuggestion = function (idx) {
        const panel = document.getElementById('extractor-merge-panel');
        const items = panel.children;
        // header(0) + suggestions (1..) — idx는 suggestions 기준
        if (items[idx + 1]) items[idx + 1].style.display = 'none';
    };

    window.extractorExecuteMerge = async function (primaryId, mergeId) {
        if (!confirm('두 claim을 병합합니다. 계속하시겠습니까?')) return;
        try {
            const res = await fetch(`${API}/claims/merge`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ primary_id: primaryId, merge_ids: [mergeId] }),
            });
            if (!res.ok) {
                const d = await res.json().catch(() => ({}));
                throw new Error(d.detail || '병합 실패');
            }
            await extractorLoadMergeSuggestions();
            loadClaims();
        } catch (e) { alert(e.message); }
    };

    // -------- 유틸 --------
    function setMsg(el, text, kind) {
        el.textContent = text;
        el.className = 'msg' + (kind === 'error' ? ' error' : '');
    }
})();
