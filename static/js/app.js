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
})();
