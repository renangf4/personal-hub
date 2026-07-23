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

    function renderResultados(resultados) {
        wrap.classList.remove('d-none');
        if (!resultados || !resultados.length) {
            lista.innerHTML = '<div class="list-group-item text-secondary">Sem resultados.</div>';
            return;
        }

        lista.innerHTML = resultados.map((r) => {
            const cls = r.ok ? 'list-group-item-success' : 'list-group-item-danger';
            const acao = r.ok && r.download_url
                ? `<a href="${r.download_url}" class="btn btn-sm btn-primary" download>
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
        const padrao = escopo ? 'Limpar' : 'Limpar Tudo';
        try {
            const resp = await fetch(infoUrl(escopo));
            const info = await resp.json();
            if (!escopo) {
                label.textContent = info.bytes > 0 ? `${padrao} (${formatBytes(info.bytes)})` : padrao;
            } else if (escopo === 'ai-chat') {
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

    async function atualizarTodosLabelsLimpar() {
        const globalBtn = document.getElementById('btn-limpar-agora');
        if (globalBtn) await atualizarLabelLimpar(globalBtn, null);
        for (const btn of document.querySelectorAll('.btn-limpar-escopo')) {
            await atualizarLabelLimpar(btn, btn.dataset.escopo);
        }
    }

    window.atualizarLabelLixo = atualizarTodosLabelsLimpar;
    atualizarTodosLabelsLimpar();

    async function executarLimpeza(btn, escopo) {
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
            } else if (escopo) {
                if (!info.arquivos) {
                    alert('Nada para limpar nesta ferramenta.');
                    return;
                }
                if (!confirm(`Remover ${info.arquivos} arquivo(s) (${formatBytes(info.bytes)}) desta ferramenta?`)) return;
            } else {
                const temArquivos = info.arquivos > 0;
                const temChats = (info.chats || 0) > 0;
                if (!temArquivos && !temChats) {
                    alert('Nada para limpar.');
                    return;
                }
                const partes = [];
                if (temArquivos) partes.push(`${info.arquivos} arquivo(s) (${formatBytes(info.bytes)})`);
                if (temChats) partes.push(`${info.chats} conversa(s)`);
                if (!confirm(`Remover ${partes.join(' e ')}?`)) return;
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
            } else if (!escopo) {
                const partes = [`${data.arquivos} arquivo(s) (${formatBytes(data.bytes)})`];
                if (data.chats) partes.push(`${data.chats} conversa(s)`);
                alert(`${partes.join(' e ')} removidos.`);
                if (typeof window.aiRecarregarAposLimpar === 'function') {
                    window.aiRecarregarAposLimpar();
                }
            } else {
                alert(`${data.arquivos} arquivo(s) removido(s) (${formatBytes(data.bytes)} liberados).`);
            }
        } catch (err) {
            alert('Erro ao limpar: ' + err.message);
        } finally {
            btn.disabled = false;
            atualizarTodosLabelsLimpar();
        }
    }

    const btnLimpar = document.getElementById('btn-limpar-agora');
    if (btnLimpar) {
        btnLimpar.addEventListener('click', () => executarLimpeza(btnLimpar, null));
    }

    document.querySelectorAll('.btn-limpar-escopo').forEach((btn) => {
        btn.addEventListener('click', () => executarLimpeza(btn, btn.dataset.escopo));
    });
})();
