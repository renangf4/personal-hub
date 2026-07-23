(function () {
    const grid = document.getElementById('loja-grid');
    const alerta = document.getElementById('loja-alerta');
    if (!grid) return;

    let ocupado = false;

    function formatBytes(b) {
        if (!b) return '0 B';
        if (b < 1024) return b + ' B';
        if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB';
        return (b / (1024 * 1024)).toFixed(2) + ' MB';
    }

    function mostrarAlerta(tipo, msg) {
        if (!alerta) return;
        alerta.className = `alert alert-${tipo}`;
        alerta.textContent = msg;
        alerta.classList.remove('d-none');
    }

    function esconderAlerta() {
        if (!alerta) return;
        alerta.classList.add('d-none');
    }

    function cardEl(slug) {
        return grid.querySelector(`[data-extra="${slug}"]`);
    }

    function setBotoesDisabled(disabled) {
        grid.querySelectorAll('button').forEach((btn) => {
            btn.disabled = disabled;
        });
    }

    function labelDados(extra) {
        if (extra.escopo_dados === 'ai-chat') {
            return extra.dados_chats > 0
                ? `Deletar dados (${extra.dados_chats})`
                : 'Deletar dados';
        }
        if (extra.dados_arquivos > 0) {
            return `Deletar dados (${formatBytes(extra.dados_bytes)})`;
        }
        return 'Deletar dados';
    }

    async function lerStream(resp, onEvento) {
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const linhas = buffer.split('\n');
            buffer = linhas.pop() || '';
            for (const linha of linhas) {
                if (!linha.trim()) continue;
                onEvento(JSON.parse(linha));
            }
        }
        if (buffer.trim()) onEvento(JSON.parse(buffer));
    }

    async function operar(slug, acao) {
        if (ocupado) return;
        ocupado = true;
        esconderAlerta();
        setBotoesDisabled(true);

        const card = cardEl(slug);
        const log = card.querySelector('.loja-log');
        log.classList.remove('d-none');
        log.textContent = '';

        const btn = card.querySelector(acao === 'instalar' ? '.btn-loja-instalar' : '.btn-loja-desinstalar');
        if (btn) {
            btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1" role="status"></span> Aguarde...`;
        }

        try {
            const resp = await fetch(`/api/loja/${slug}/${acao}`, { method: 'POST' });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

            let resultado = null;
            await lerStream(resp, (ev) => {
                if (ev.tipo === 'log') {
                    log.textContent += ev.linha + '\n';
                    log.scrollTop = log.scrollHeight;
                } else if (ev.tipo === 'erro') {
                    resultado = { ok: false, msg: ev.msg };
                } else if (ev.tipo === 'fim') {
                    resultado = ev;
                }
            });

            if (!resultado || !resultado.ok) {
                mostrarAlerta('danger', (resultado && resultado.msg) || 'Operacao falhou');
                await atualizarCards();
                return;
            }

            mostrarAlerta('success', resultado.msg || 'Concluido');
            await atualizarCards();
            if (typeof window.atualizarLabelLixo === 'function') window.atualizarLabelLixo();
        } catch (err) {
            mostrarAlerta('danger', err.message || 'Erro na operacao');
            await atualizarCards();
        } finally {
            ocupado = false;
            setBotoesDisabled(false);
        }
    }

    async function deletarDados(escopo) {
        if (ocupado) return;
        ocupado = true;
        esconderAlerta();
        setBotoesDisabled(true);
        try {
            const infoResp = await fetch(`/api/limpar-info/${escopo}`);
            const info = await infoResp.json();

            if (escopo === 'ai-chat') {
                if (!info.chats) {
                    alert('Nenhuma conversa para apagar.');
                    return;
                }
                if (!confirm(`Apagar ${info.chats} conversa(s) desta ferramenta?`)) return;
            } else {
                if (!info.arquivos) {
                    alert('Nenhum arquivo para apagar.');
                    return;
                }
                if (!confirm(`Apagar ${info.arquivos} arquivo(s) (${formatBytes(info.bytes)}) desta ferramenta?`)) return;
            }

            const resp = await fetch(`/api/limpar-agora/${escopo}`, { method: 'POST' });
            const data = await resp.json();
            if (escopo === 'ai-chat') {
                mostrarAlerta('success', `${data.chats || 0} conversa(s) removida(s).`);
            } else {
                mostrarAlerta('success', `${data.arquivos} arquivo(s) removidos (${formatBytes(data.bytes)}).`);
            }
            await atualizarCards();
            if (typeof window.atualizarLabelLixo === 'function') window.atualizarLabelLixo();
        } catch (err) {
            mostrarAlerta('danger', err.message || 'Erro ao apagar dados');
        } finally {
            ocupado = false;
            setBotoesDisabled(false);
        }
    }

    function renderCard(extra) {
        const pkgs = (extra.packages || []).map((pkg) => `
            <li class="loja-pkgs__item">
                <i class="bi bi-box-seam"></i>
                <code>${escapeHtml(pkg)}</code>
            </li>
        `).join('');
        const status = extra.instalado
            ? '<span class="badge text-bg-success loja-status">Instalado</span>'
            : '<span class="badge text-bg-secondary loja-status">Disponivel</span>';
        const pacote = extra.instalado
            ? `<button type="button" class="btn btn-outline-danger btn-loja-desinstalar" data-slug="${extra.slug}">
                   <i class="bi bi-box-arrow-down"></i> Desinstalar
               </button>`
            : `<button type="button" class="btn btn-primary btn-loja-instalar" data-slug="${extra.slug}">
                   <i class="bi bi-download"></i> Instalar
               </button>`;
        const dados = `<button type="button" class="btn btn-sm btn-limpar btn-loja-dados" data-escopo="${extra.escopo_dados}" title="Apaga arquivos/conversas desta ferramenta">
                <i class="bi bi-trash3"></i> <span class="btn-loja-dados-label">${escapeHtml(labelDados(extra))}</span>
            </button>`;

        return `
        <div class="col-12 col-md-6" data-extra="${extra.slug}" data-escopo="${extra.escopo_dados}">
            <div class="card h-100 tool-card hub-card">
                <div class="card-body d-flex flex-column p-4">
                    <div class="d-flex align-items-center gap-3 mb-3">
                        <span class="loja-icon d-inline-flex align-items-center justify-content-center">
                            <i class="bi ${extra.icone} fs-4"></i>
                        </span>
                        <div>
                            <h2 class="h5 mb-1 fw-semibold">${escapeHtml(extra.nome)}</h2>
                            ${status}
                        </div>
                    </div>
                    <p class="card-text text-secondary flex-grow-1 small">${escapeHtml(extra.descricao)}</p>
                    <ul class="loja-pkgs list-unstyled small text-secondary mb-3">${pkgs}</ul>
                    <div class="d-flex flex-wrap gap-2">${pacote}${dados}</div>
                    <pre class="loja-log form-control mt-3 mb-0 d-none small font-monospace"></pre>
                </div>
            </div>
        </div>`;
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, (c) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));
    }

    async function atualizarCards() {
        const resp = await fetch('/api/loja');
        const data = await resp.json();
        grid.innerHTML = (data.extras || []).map(renderCard).join('');
    }

    // Atualiza labels de tamanho na carga inicial
    atualizarCards();

    grid.addEventListener('click', (e) => {
        const instalar = e.target.closest('.btn-loja-instalar');
        const desinstalar = e.target.closest('.btn-loja-desinstalar');
        const dados = e.target.closest('.btn-loja-dados');
        if (instalar) {
            operar(instalar.dataset.slug, 'instalar');
        } else if (desinstalar) {
            const slug = desinstalar.dataset.slug;
            if (confirm('Remover este pacote? A ferramenta sumira da home. Os arquivos gerados nao sao apagados.')) {
                operar(slug, 'desinstalar');
            }
        } else if (dados) {
            deletarDados(dados.dataset.escopo);
        }
    });
})();
