(function () {
    const form = document.getElementById('form-processar');
    const status = document.getElementById('status');
    const wrap = document.getElementById('resultados-wrap');
    const lista = document.getElementById('resultados');

    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const slug = form.dataset.slug || (form.elements['formato'] && form.elements['formato'].value);
            const formData = new FormData(form);

            status.classList.remove('d-none');
            wrap.classList.add('d-none');
            lista.innerHTML = '';

            try {
                const resp = await fetch(`/tool/${slug}/processar`, {
                    method: 'POST',
                    body: formData,
                });

                if (!resp.ok) {
                    const txt = await resp.text();
                    throw new Error(txt || `HTTP ${resp.status}`);
                }

                const data = await resp.json();
                renderResultados(data.resultados);
            } catch (err) {
                lista.innerHTML = `<div class="list-group-item list-group-item-danger">Erro: ${err.message}</div>`;
                wrap.classList.remove('d-none');
            } finally {
                status.classList.add('d-none');
                if (typeof window.atualizarLabelLixo === 'function') window.atualizarLabelLixo();
            }
        });
    }

    function modoPreviewCards() {
        const controles = (wrap && (wrap.getAttribute('data-controles') || wrap.dataset.controles)) || '';
        if (controles === 'video') return 'video';
        if (controles === 'imagem' || controles === 'wp-screenshot') return 'imagem';

        const escopo = (
            document.getElementById('btn-storage')
            || document.querySelector('.btn-limpar-escopo')
        );
        const esc = (escopo && escopo.getAttribute('data-escopo')) || '';
        if (esc === 'video') return 'video';
        if (esc === 'imagem' || esc === 'wp-screenshot') return 'imagem';

        const path = location.pathname || '';
        if (path.includes('/categoria/video') || /\/tool\/convert-(mp4|webm|gif|mkv|mov)\b/.test(path)) {
            return 'video';
        }
        if (
            path.includes('/categoria/imagem')
            || path.includes('wp-screenshot')
            || /\/tool\/convert-/.test(path)
        ) {
            return 'imagem';
        }
        return null;
    }

    function mediaUrl(url) {
        if (!url) return '';
        try {
            const u = new URL(url, location.origin);
            const parts = u.pathname.split('/').map((p, i, arr) => (
                i === arr.length - 1 && p ? encodeURIComponent(decodeURIComponent(p)) : p
            ));
            u.pathname = parts.join('/');
            return u.pathname + u.search;
        } catch (_) {
            return url;
        }
    }

    function renderResultados(resultados) {
        wrap.classList.remove('d-none');
        if (!resultados || !resultados.length) {
            lista.className = 'list-group';
            lista.innerHTML = '<div class="list-group-item text-secondary">Sem resultados.</div>';
            return;
        }

        const modo = modoPreviewCards();
        if (modo === 'imagem' || modo === 'video') {
            lista.className = 'resultados-preview' + (modo === 'video' ? ' resultados-preview--video' : '');
            try {
                lista.innerHTML = resultados.map((r) =>
                    modo === 'video' ? renderResultadoVideo(r) : renderResultadoImagem(r)
                ).join('');
                hidratarPreviews(lista);
            } catch (err) {
                console.error('Falha ao renderizar cards:', err);
                lista.className = 'list-group';
                lista.innerHTML = `<div class="list-group-item list-group-item-danger">Erro ao montar preview: ${escapeHtml(err.message || err)}</div>`;
            }
            return;
        }

        lista.className = 'list-group';
        lista.innerHTML = resultados.map((r) => {
            const cls = r.ok ? 'list-group-item-success' : 'list-group-item-danger';
            const acao = r.ok && r.download_url
                ? `<a href="${escapeHtml(mediaUrl(r.download_url))}" class="btn btn-sm btn-primary" download>
                       <i class="bi bi-download"></i> Baixar
                   </a>`
                : '';
            return `
                <div class="list-group-item ${cls} d-flex justify-content-between align-items-center flex-wrap gap-2">
                    <div>
                        <div><strong>${escapeHtml(r.entrada)}</strong></div>
                        <div class="resultado-msg">${escapeHtml(r.msg || '')}</div>
                    </div>
                    ${acao}
                </div>
            `;
        }).join('');
    }

    function renderResultadoImagem(r) {
        if (!r.ok || !r.download_url || !r.saida) {
            return renderResultadoCardErro(r);
        }
        const nome = r.saida;
        const url = mediaUrl(r.download_url);
        const peso = r.bytes != null ? formatBytes(r.bytes) : '';
        return `
            <a href="${escapeHtml(url)}" class="resultado-card" download="${escapeHtml(nome)}" title="Baixar ${escapeHtml(nome)}${peso ? ` (${peso})` : ''}">
                <div class="resultado-card__preview">
                    <img data-preview-src="${escapeHtml(url)}" alt="${escapeHtml(nome)}" loading="lazy">
                </div>
                <div class="resultado-card__meta">
                    <div class="resultado-card__info">
                        <span class="resultado-card__nome">${escapeHtml(nome)}</span>
                        ${peso ? `<span class="resultado-card__peso">${escapeHtml(peso)}</span>` : ''}
                    </div>
                    <span class="resultado-card__acao"><i class="bi bi-download"></i></span>
                </div>
            </a>
        `;
    }

    function renderResultadoVideo(r) {
        if (!r.ok || !r.download_url || !r.saida) {
            return renderResultadoCardErro(r);
        }
        const nome = r.saida;
        const url = mediaUrl(r.download_url);
        const peso = r.bytes != null ? formatBytes(r.bytes) : '';
        const ext = (nome.split('.').pop() || '').toLowerCase();
        let preview;
        if (ext === 'gif') {
            preview = `<img data-preview-src="${escapeHtml(url)}" alt="${escapeHtml(nome)}" loading="lazy">`;
        } else if (ext === 'mp4' || ext === 'webm' || ext === 'mov') {
            preview = `<video data-preview-src="${escapeHtml(url)}" muted playsinline loop preload="metadata"></video>`;
        } else {
            preview = `<div class="resultado-card__placeholder"><i class="bi bi-film"></i></div>`;
        }
        return `
            <a href="${escapeHtml(url)}" class="resultado-card resultado-card--video" download="${escapeHtml(nome)}" title="Baixar ${escapeHtml(nome)}${peso ? ` (${peso})` : ''}">
                <div class="resultado-card__preview resultado-card__preview--video">
                    ${preview}
                </div>
                <div class="resultado-card__meta">
                    <div class="resultado-card__info">
                        <span class="resultado-card__nome">${escapeHtml(nome)}</span>
                        ${peso ? `<span class="resultado-card__peso">${escapeHtml(peso)}</span>` : ''}
                    </div>
                    <span class="resultado-card__acao"><i class="bi bi-download"></i></span>
                </div>
            </a>
        `;
    }

    function renderResultadoCardErro(r) {
        return `
            <div class="resultado-card resultado-card--erro">
                <div class="resultado-card__preview resultado-card__preview--erro">
                    <i class="bi bi-exclamation-triangle"></i>
                </div>
                <div class="resultado-card__meta">
                    <span class="resultado-card__nome">${escapeHtml(r.entrada || 'Erro')}</span>
                    <span class="resultado-card__hint">${escapeHtml(r.msg || 'Falha')}</span>
                </div>
            </div>
        `;
    }

    function hidratarPreviews(container) {
        container.querySelectorAll('img[data-preview-src]').forEach(async (img) => {
            const src = img.getAttribute('data-preview-src');
            if (!src) return;
            try {
                const resp = await fetch(src);
                if (!resp.ok) throw new Error('preview');
                const blob = await resp.blob();
                const objectUrl = URL.createObjectURL(blob);
                img.onload = () => URL.revokeObjectURL(objectUrl);
                img.src = objectUrl;
            } catch (_) {
                img.alt = 'Preview indisponivel';
            }
        });

        container.querySelectorAll('video[data-preview-src]').forEach(async (video) => {
            const src = video.getAttribute('data-preview-src');
            if (!src) return;
            try {
                const resp = await fetch(src);
                if (!resp.ok) throw new Error('preview');
                const blob = await resp.blob();
                const objectUrl = URL.createObjectURL(blob);
                video.src = objectUrl;
                video.addEventListener('loadeddata', () => {
                    video.play().catch(() => {});
                }, { once: true });
            } catch (_) {
                video.replaceWith(Object.assign(document.createElement('div'), {
                    className: 'resultado-card__placeholder',
                    innerHTML: '<i class="bi bi-film"></i>',
                }));
            }
        });
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, (c) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));
    }

    function formatBytes(b) {
        if (!b) return '0 B';
        if (b < 1024) return b + ' B';
        if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB';
        return (b / (1024 * 1024)).toFixed(2) + ' MB';
    }

    function infoUrl(escopo) {
        return escopo ? `/api/limpar-info/${escopo}` : '/api/limpar-info';
    }

    function limparUrl(escopo) {
        return escopo ? `/api/limpar-agora/${escopo}` : '/api/limpar-agora';
    }

    async function atualizarLabelLimpar(btn, escopo) {
        const label = btn.querySelector('.btn-limpar-escopo-label, #btn-limpar-label');
        if (!label) return;
        const isTemp = btn.classList.contains('btn-limpar-escopo') && escopo && escopo !== 'ai-chat';
        const padrao = isTemp ? 'Limpar dados temporarios' : (escopo ? 'Limpar' : 'Limpar');
        try {
            const resp = await fetch(infoUrl(escopo));
            const info = await resp.json();
            if (escopo === 'ai-chat') {
                label.textContent = info.chats > 0 ? `Limpar (${info.chats})` : padrao;
            } else if (info.arquivos > 0) {
                label.textContent = `${padrao} (${formatBytes(info.bytes)})`;
            } else {
                label.textContent = padrao;
            }
        } catch (err) {
            label.textContent = padrao;
        }
    }

    async function atualizarLabelTemporarios() {
        const btn = document.getElementById('btn-limpar-temporarios');
        if (!btn) return;
        const label = btn.querySelector('.btn-limpar-temp-label');
        const padrao = 'Limpar arquivos temporarios';
        try {
            const resp = await fetch('/api/limpar-info/temporarios');
            const info = await resp.json();
            if (label) {
                label.textContent = info.arquivos > 0
                    ? `${padrao} (${formatBytes(info.bytes)})`
                    : padrao;
            }
        } catch (_) {
            if (label) label.textContent = padrao;
        }
    }

    async function atualizarTodosLabelsLimpar() {
        for (const btn of document.querySelectorAll('.btn-limpar-escopo')) {
            await atualizarLabelLimpar(btn, btn.dataset.escopo);
        }
        await atualizarLabelTemporarios();
    }

    window.atualizarLabelLixo = atualizarTodosLabelsLimpar;
    atualizarTodosLabelsLimpar();

    function limparPainelResultados() {
        if (!wrap || !lista) return;
        lista.querySelectorAll('video').forEach((v) => {
            try {
                v.pause();
                v.removeAttribute('src');
                v.load();
            } catch (_) { /* ignore */ }
        });
        lista.innerHTML = '';
        lista.className = 'list-group';
        wrap.classList.add('d-none');
    }

    function removerResultadoPorNome(nome) {
        if (!lista || !nome) return;
        lista.querySelectorAll('a.resultado-card').forEach((card) => {
            const dl = card.getAttribute('download') || '';
            const href = card.getAttribute('href') || '';
            if (dl === nome || decodeURIComponent(href).endsWith('/' + nome) || href.endsWith('/' + encodeURIComponent(nome))) {
                const media = card.querySelector('video');
                if (media) {
                    try {
                        media.pause();
                        media.removeAttribute('src');
                        media.load();
                    } catch (_) { /* ignore */ }
                }
                card.remove();
            }
        });
        if (!lista.querySelector('.resultado-card')) {
            limparPainelResultados();
        }
    }

    async function executarLimpeza(btn, escopo) {
        if (!escopo) return;
        btn.disabled = true;
        try {
            const infoResp = await fetch(infoUrl(escopo));
            const info = await infoResp.json();

            if (escopo === 'ai-chat') {
                if (!info.chats) {
                    alert('Nenhuma conversa para limpar.');
                    return;
                }
                if (!confirm(`Apagar ${info.chats} conversa(s)?`)) return;
            } else {
                if (!info.arquivos) {
                    alert('Nenhum dado temporario para limpar.');
                    return;
                }
                if (!confirm(`Remover ${info.arquivos} arquivo(s) temporarios (${formatBytes(info.bytes)})?`)) return;
            }

            const resp = await fetch(limparUrl(escopo), { method: 'POST' });
            const data = await resp.json();
            if (escopo === 'ai-chat') {
                alert(`${data.chats || 0} conversa(s) removida(s).`);
                if (typeof window.aiRecarregarAposLimpar === 'function') {
                    window.aiRecarregarAposLimpar();
                } else {
                    location.reload();
                }
            } else {
                limparPainelResultados();
                alert(`${data.arquivos} arquivo(s) removido(s) (${formatBytes(data.bytes)} liberados).`);
            }
        } catch (err) {
            alert('Erro ao limpar: ' + err.message);
        } finally {
            btn.disabled = false;
            atualizarTodosLabelsLimpar();
        }
    }

    document.querySelectorAll('.btn-limpar-escopo').forEach((btn) => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            executarLimpeza(btn, btn.dataset.escopo);
        });
    });

    async function destruirTudo(btn) {
        const msg1 =
            'DESTRUIR TUDO?\n\n' +
            'Isso apaga de forma permanente:\n' +
            '- Uploads e arquivos gerados\n' +
            '- Conversas da IA\n' +
            '- Cofres (.hubvault)\n' +
            '- Dados fake (.hubfake)\n' +
            '- Authenticator 2FA (.hubtotp)\n' +
            '- Senhas salvas do PDF\n' +
            '- API keys (Shodan, AbuseIPDB, VirusTotal)\n\n' +
            'Nao da pra desfazer.';
        if (!confirm(msg1)) return;
        if (!confirm('Confirma mesmo? Ultima chance antes de apagar tudo.')) return;

        btn.disabled = true;
        try {
            const resp = await fetch('/api/limpar-agora', { method: 'POST' });
            const data = await resp.json();
            const partes = [
                `${data.arquivos || 0} arquivo(s) (${formatBytes(data.bytes || 0)})`,
                `${data.chats || 0} conversa(s)`,
                `${data.senhas || 0} senha(s) PDF`,
                `${data.keys || 0} API key(s)`,
            ];
            alert('Destruido:\n' + partes.join('\n'));
            location.href = '/';
        } catch (err) {
            alert('Erro ao destruir: ' + err.message);
        } finally {
            btn.disabled = false;
        }
    }

    async function limparTemporarios(btn) {
        btn.disabled = true;
        try {
            const infoResp = await fetch('/api/limpar-info/temporarios');
            const info = await infoResp.json();
            if (!info.arquivos) {
                alert('Nenhum arquivo temporario para limpar.');
                return;
            }
            if (!confirm(
                `Limpar arquivos temporarios?\n\n` +
                `Remove uploads/saidas de video, imagem, screenshot WP e PDF.\n` +
                `${info.arquivos} arquivo(s) (${formatBytes(info.bytes)}).\n\n` +
                `Nao apaga cofres, 2FA, chats nem senhas salvas.`
            )) return;

            const resp = await fetch('/api/limpar-agora/temporarios', { method: 'POST' });
            const data = await resp.json();
            alert(`${data.arquivos} arquivo(s) removido(s) (${formatBytes(data.bytes)} liberados).`);
            if (location.pathname === '/') location.reload();
            else atualizarTodosLabelsLimpar();
        } catch (err) {
            alert('Erro ao limpar: ' + err.message);
        } finally {
            btn.disabled = false;
        }
    }

    const btnDestruir = document.getElementById('btn-destruir-tudo');
    if (btnDestruir) {
        btnDestruir.addEventListener('click', () => destruirTudo(btnDestruir));
    }

    const btnTemp = document.getElementById('btn-limpar-temporarios');
    if (btnTemp) {
        btnTemp.addEventListener('click', () => limparTemporarios(btnTemp));
    }

    /* ——— Storage browser (imagem / video) ——— */
    const btnStorage = document.getElementById('btn-storage');
    const modalStorageEl = document.getElementById('modal-storage');
    if (btnStorage && modalStorageEl) {
        const storageEscopo = btnStorage.dataset.escopo;
        const storageGrid = document.getElementById('storage-grid');
        const storageVazio = document.getElementById('storage-vazio');
        const storageResumo = document.getElementById('storage-resumo');
        const btnApagarTudo = document.getElementById('btn-storage-apagar-tudo');
        const modalStorage = bootstrap.Modal.getOrCreateInstance(modalStorageEl);

        const IMG_EXT = new Set(['.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff']);
        const VID_EXT = new Set(['.mp4', '.webm', '.mov']);

        function storageUrl(item, download) {
            const base = `/api/storage/${encodeURIComponent(storageEscopo)}/${encodeURIComponent(item.kind)}/${encodeURIComponent(item.sessao_id)}/${encodeURIComponent(item.nome)}`;
            return download ? `${base}?inline=0` : `${base}?inline=1`;
        }

        function renderStorageCard(item) {
            const peso = formatBytes(item.bytes);
            const tipo = item.kind === 'upload' ? 'Upload' : 'Saida';
            const ext = (item.ext || '').toLowerCase();
            let media = `<div class="resultado-card__placeholder"><i class="bi bi-file-earmark"></i></div>`;
            if (IMG_EXT.has(ext)) {
                media = `<img data-preview-src="${escapeHtml(storageUrl(item))}" alt="${escapeHtml(item.nome)}" loading="lazy">`;
            } else if (VID_EXT.has(ext)) {
                media = `<video data-preview-src="${escapeHtml(storageUrl(item))}" muted playsinline loop preload="metadata"></video>`;
            } else if (ext === '.mkv' || ext === '.avi' || ext === '.m4v') {
                media = `<div class="resultado-card__placeholder"><i class="bi bi-film"></i></div>`;
            }

            return `
                <div class="resultado-card storage-card" data-kind="${escapeHtml(item.kind)}" data-sessao="${escapeHtml(item.sessao_id)}" data-nome="${escapeHtml(item.nome)}">
                    <a href="${escapeHtml(storageUrl(item, true))}" class="storage-card__preview resultado-card__preview${VID_EXT.has(ext) || ext === '.mkv' ? ' resultado-card__preview--video' : ''}" download="${escapeHtml(item.nome)}" title="Baixar ${escapeHtml(item.nome)}">
                        ${media}
                    </a>
                    <div class="resultado-card__meta">
                        <div class="resultado-card__info">
                            <span class="resultado-card__nome" title="${escapeHtml(item.nome)}">${escapeHtml(item.nome)}</span>
                            <span class="resultado-card__peso">${escapeHtml(peso)} · ${tipo}</span>
                        </div>
                        <button type="button" class="btn btn-sm btn-limpar storage-card__del" title="Apagar arquivo">
                            <i class="bi bi-trash3"></i>
                        </button>
                    </div>
                </div>
            `;
        }

        async function carregarStorage() {
            storageResumo.textContent = 'Carregando...';
            storageGrid.innerHTML = '';
            storageVazio.classList.add('d-none');
            try {
                const resp = await fetch(`/api/storage/${encodeURIComponent(storageEscopo)}`);
                const data = await resp.json();
                if (!resp.ok || !data.ok) throw new Error(data.detail || 'Falha ao listar');
                const itens = data.itens || [];
                storageResumo.textContent = itens.length
                    ? `${itens.length} arquivo(s) · ${formatBytes(data.bytes || 0)}`
                    : 'Vazio';
                if (!itens.length) {
                    storageVazio.classList.remove('d-none');
                    return;
                }
                storageGrid.innerHTML = itens.map(renderStorageCard).join('');
                hidratarPreviews(storageGrid);
            } catch (err) {
                storageResumo.textContent = 'Erro ao carregar';
                storageVazio.textContent = err.message || 'Erro';
                storageVazio.classList.remove('d-none');
            }
        }

        btnStorage.addEventListener('click', () => {
            modalStorage.show();
            carregarStorage();
        });

        storageGrid.addEventListener('click', async (e) => {
            const btn = e.target.closest('.storage-card__del');
            if (!btn) return;
            e.preventDefault();
            e.stopPropagation();
            const card = btn.closest('.storage-card');
            if (!card) return;
            const { kind, sessao, nome } = card.dataset;
            if (!confirm(`Apagar "${nome}"?`)) return;
            btn.disabled = true;
            try {
                const resp = await fetch(
                    `/api/storage/${encodeURIComponent(storageEscopo)}/${encodeURIComponent(kind)}/${encodeURIComponent(sessao)}/${encodeURIComponent(nome)}`,
                    { method: 'DELETE' }
                );
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(data.detail || 'Falha ao apagar');
                if (kind === 'output') removerResultadoPorNome(nome);
                await carregarStorage();
                if (typeof window.atualizarLabelLixo === 'function') window.atualizarLabelLixo();
            } catch (err) {
                alert('Erro ao apagar: ' + err.message);
                btn.disabled = false;
            }
        });

        if (btnApagarTudo) {
            btnApagarTudo.addEventListener('click', async () => {
                try {
                    const infoResp = await fetch(infoUrl(storageEscopo));
                    const info = await infoResp.json();
                    if (!info.arquivos) {
                        alert('Nenhum arquivo para apagar.');
                        return;
                    }
                    if (!confirm(`Apagar todos os ${info.arquivos} arquivo(s) (${formatBytes(info.bytes)})?`)) return;
                    btnApagarTudo.disabled = true;
                    const resp = await fetch(limparUrl(storageEscopo), { method: 'POST' });
                    const data = await resp.json();
                    if (!resp.ok) throw new Error(data.detail || 'Falha');
                    limparPainelResultados();
                    await carregarStorage();
                    if (typeof window.atualizarLabelLixo === 'function') window.atualizarLabelLixo();
                } catch (err) {
                    alert('Erro ao apagar tudo: ' + err.message);
                } finally {
                    btnApagarTudo.disabled = false;
                }
            });
        }
    }
})();
