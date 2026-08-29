(function () {
    const statusBadge = document.getElementById('ai-status-badge');
    const gate = document.getElementById('ai-gate');
    const gateMsg = document.getElementById('ai-gate-msg');
    const gateTitulo = document.getElementById('ai-gate-titulo');
    const gateErro = document.getElementById('ai-gate-erro');
    const presetsWrap = document.getElementById('ai-presets');
    const btnInstalar = document.getElementById('ai-btn-instalar');
    const btnIniciar = document.getElementById('ai-btn-iniciar');
    const btnVoltar = document.getElementById('ai-btn-voltar');
    const pullWrap = document.getElementById('ai-pull-wrap');
    const pullBar = document.getElementById('ai-pull-bar');
    const pullPercent = document.getElementById('ai-pull-percent');
    const pullStatus = document.getElementById('ai-pull-status');
    const pullDetalhe = document.getElementById('ai-pull-detalhe');
    let pullSlugLocal = '';

    const chat = document.getElementById('ai-chat');
    const listaChats = document.getElementById('ai-lista-chats');
    const btnNovoChat = document.getElementById('ai-novo-chat');
    const tituloEl = document.getElementById('ai-chat-titulo');
    const modeloSelect = document.getElementById('ai-modelo-select');
    const ctxSelect = document.getElementById('ai-ctx-select');
    const btnCtxInfo = document.getElementById('ai-btn-ctx-info');
    const ctxInfo = document.getElementById('ai-ctx-info');
    const btnCtxFechar = document.getElementById('ai-btn-ctx-fechar');
    const ramLivreEl = document.getElementById('ai-ram-livre');
    const btnGerenciar = document.getElementById('ai-btn-gerenciar');
    const btnRenomear = document.getElementById('ai-btn-renomear');
    const btnExcluir = document.getElementById('ai-btn-excluir');
    const btnLiberarMem = document.getElementById('ai-btn-liberar-mem');
    const mensagensEl = document.getElementById('ai-mensagens');
    const form = document.getElementById('ai-form');
    const input = document.getElementById('ai-input');
    const btnEnviar = document.getElementById('ai-btn-enviar');
    const btnParar = document.getElementById('ai-btn-parar');
    const btnAnexo = document.getElementById('ai-btn-anexo');
    const fileInput = document.getElementById('ai-file');
    const anexosEl = document.getElementById('ai-anexos');

    const LS_MODELO = 'ai_chat_modelo';
    const LS_CTX = 'ai_chat_num_ctx';
    let chatAtual = null;
    let chatsCache = [];
    let enviando = false;
    /** @type {AbortController|null} */
    let envioAbort = null;
    let ultimoStatus = null;
    let modoGerenciar = false;
    const CTX_PADRAO = 16384;
    /** @type {File[]} */
    let anexosPendentes = [];
    const MAX_ANEXOS = 5;

    marked.setOptions({
        breaks: true,
        gfm: true,
        highlight(code, lang) {
            if (lang && hljs.getLanguage(lang)) {
                try { return hljs.highlight(code, { language: lang }).value; } catch (_) {}
            }
            try { return hljs.highlightAuto(code).value; } catch (_) { return code; }
        },
    });

    function setStatus(estado, texto) {
        const map = {
            ok: 'text-bg-success',
            warn: 'text-bg-warning',
            erro: 'text-bg-danger',
            off: 'text-bg-secondary',
        };
        statusBadge.className = 'badge ' + (map[estado] || 'text-bg-secondary');
        statusBadge.innerHTML = `<i class="bi bi-circle-fill me-1"></i> ${texto}`;
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, (c) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));
    }

    function formatBytes(b) {
        if (!b && b !== 0) return '-';
        if (b < 1024) return b + ' B';
        if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB';
        if (b < 1024 * 1024 * 1024) return (b / (1024 * 1024)).toFixed(1) + ' MB';
        return (b / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
    }

    function formatGb(bytes) {
        if (!bytes && bytes !== 0) return '-';
        const gb = bytes / (1024 * 1024 * 1024);
        if (gb >= 10) return gb.toFixed(0) + ' GB';
        return gb.toFixed(1) + ' GB';
    }

    function livreGbUtil(ram) {
        if (!ram || !ram.disponivel) return null;
        return ram.disponivel / (1024 * 1024 * 1024);
    }

    function folgaGb() {
        const bytes = (ultimoStatus && ultimoStatus.ram_folga_bytes) || (1.5 * 1024 * 1024 * 1024);
        return bytes / (1024 * 1024 * 1024);
    }

    function contextoExcedeMemoria(ctx) {
        if (!ctx) return false;
        if (typeof ctx.cabe === 'boolean') return !ctx.cabe;
        const livre = livreGbUtil(ultimoStatus && ultimoStatus.ram);
        if (livre == null || ctx.ram_gb == null) return false;
        return ctx.ram_gb + folgaGb() > livre;
    }

    function rotuloContexto(c, sugerido) {
        const base = `${c.label} — ${c.nome}`;
        const ramTxt = c.ram ? ` (${c.ram})` : '';
        if (c.tokens === sugerido) return `${base}${ramTxt} · sugerido`;
        if (contextoExcedeMemoria(c)) {
            const modo = (ultimoStatus && ultimoStatus.memoria_modo) === 'gpu'
                ? 'acima da VRAM/RAM'
                : 'acima da RAM livre';
            return `${base}${ramTxt} · ${modo}`;
        }
        return `${base}${ramTxt}`;
    }

    function atualizarRam(ram, opts) {
        if (!ramLivreEl) return;
        const vram = (opts && opts.vram) || (ultimoStatus && ultimoStatus.vram) || null;
        if ((!ram || !ram.disponivel) && (!vram || !vram.disponivel)) {
            ramLivreEl.classList.add('d-none');
            ramLivreEl.textContent = '';
            return;
        }

        const lista = (opts && opts.contextos) || (ultimoStatus && ultimoStatus.contextos) || [];
        const tokens = opts && opts.tokens != null
            ? opts.tokens
            : (ctxSelect ? parseInt(ctxSelect.value, 10) : NaN);
        const atual = lista.find((c) => c.tokens === tokens);
        const excede = contextoExcedeMemoria(atual);
        const modoGpu = (ultimoStatus && ultimoStatus.memoria_modo) === 'gpu' || !!(vram && vram.disponivel);

        const partes = [];
        let title = '';
        let pctRef = 100;

        if (vram && vram.disponivel != null && vram.total) {
            const usadaV = formatGb(vram.usada != null ? vram.usada : (vram.total - vram.disponivel));
            const totalV = formatGb(vram.total);
            const livreV = formatGb(vram.disponivel);
            pctRef = Math.round((vram.disponivel / vram.total) * 100);
            partes.push(
                `<i class="bi bi-gpu-card me-1"></i>VRAM: <strong>${usadaV}</strong> / ${totalV}`
            );
            title = (vram.nome ? vram.nome + ' — ' : '') +
                `${usadaV} em uso de ${totalV} (${livreV} livre p/ modelos).`;
        }
        if (ram && ram.disponivel != null && ram.total) {
            const usada = ram.usada != null ? ram.usada : (ram.total - ram.disponivel);
            const usadaFmt = formatGb(usada);
            const total = formatGb(ram.total);
            const livre = formatGb(ram.disponivel);
            const pctRam = Math.round((ram.disponivel / ram.total) * 100);
            if (!modoGpu) pctRef = pctRam;
            partes.push(
                (partes.length ? ' · ' : '') +
                `<i class="bi bi-memory me-1"></i>RAM: <strong>${usadaFmt}</strong> / ${total}`
            );
            title = (title ? title + ' ' : '') +
                `RAM: ${usadaFmt} em uso de ${total} (como no monitor). ` +
                `${livre} disponivel p/ carregar modelos.`;
        }

        ramLivreEl.classList.remove('d-none', 'ai-chat__ram--baixa', 'ai-chat__ram--ok', 'ai-chat__ram--aviso');
        const modeloPesado = ultimoStatus && ultimoStatus.modelo_cabe === false;
        if (excede || modeloPesado) {
            ramLivreEl.classList.add('ai-chat__ram--aviso');
            const avisoCtx = excede
                ? '· contexto pode passar'
                : '· modelo pesado p/ o servidor';
            ramLivreEl.innerHTML =
                partes.join('') +
                ` <span class="ai-chat__ram-aviso">${avisoCtx}</span>`;
            const est = atual && atual.ram_gb != null ? `~${atual.ram_gb} GB` : '?';
            const peso = ultimoStatus && ultimoStatus.modelo_ram_estimada_gb != null
                ? `~${ultimoStatus.modelo_ram_estimada_gb} GB`
                : est;
            ramLivreEl.title =
                (modeloPesado
                    ? `Modelo selecionado estima ${peso} no servidor. `
                    : `Contexto selecionado estima ${est}. `) + title +
                (modeloPesado ? ' Escolha um modelo menor.' : ' Pode ficar lento ou usar overflow CPU/RAM.');
        } else {
            ramLivreEl.classList.add(pctRef < 20 ? 'ai-chat__ram--baixa' : 'ai-chat__ram--ok');
            ramLivreEl.innerHTML = partes.join('');
            ramLivreEl.title = title.trim();
        }
    }

    function urlStatus() {
        return '/api/ai/status?modelo=' + encodeURIComponent(modeloAtual());
    }

    async function verificarStatus() {
        try {
            const resp = await fetch(urlStatus());
            const data = await resp.json();
            ultimoStatus = data;
            atualizarRam(data.ram, { vram: data.vram });

            if (!data.ollama_ativo) {
                setStatus('erro', 'Ollama offline');
                if (!data.ollama_instalado) {
                    if (data.sistema === 'Windows') {
                        mostrarGate('Ollama nao instalado',
                            `Ollama nao esta instalado neste computador.<br>
                             Clique para baixar e instalar automaticamente.`,
                            { instalar: true }
                        );
                    } else if (data.sistema === 'Linux') {
                        mostrarGate('Ollama nao instalado',
                            `Sera instalado no <strong>servidor</strong> onde o hub roda (nao no seu PC).<br>
                             Clique para instalar automaticamente.`,
                            { instalar: true }
                        );
                    } else if (data.sistema === 'Darwin') {
                        mostrarGate('Ollama nao instalado',
                            `Baixe em
                             <a href="https://ollama.com/download" target="_blank" rel="noopener">ollama.com/download</a>
                             e instale o app.`,
                            {}
                        );
                    } else {
                        mostrarGate('Ollama nao instalado',
                            `No terminal rode:<br>
                             <code>curl -fsSL https://ollama.com/install.sh | sh</code>`,
                            {}
                        );
                    }
                } else {
                    mostrarGate('Ollama parado',
                        `Ollama esta instalado mas nao esta rodando em <code>localhost:11434</code>.<br>
                         Clique para iniciar o servico.`,
                        { iniciar: true }
                    );
                }
                return false;
            }

            const algumBaixado = (data.presets || []).some(p => p.baixado);
            if (!algumBaixado) {
                setStatus('warn', 'Nenhum modelo');
                mostrarGate('Escolha um modelo',
                    `Nenhum modelo foi baixado ainda. Selecione abaixo qual instalar.`,
                    { presets: true, presetsData: data.presets }
                );
                aplicarPullDoStatus(data);
                return false;
            }

            setStatus('ok', 'Pronto');
            if (modoGerenciar) {
                mostrarGate('Configurar modelos',
                    'Baixe novos modelos ou remova os que nao usa mais para liberar espaco.',
                    { presets: true, presetsData: data.presets, gerenciar: true, voltar: true }
                );
                atualizarSeletorModelo(data.presets);
                atualizarSeletorContexto(data.contextos, data.contexto_sugerido || data.contexto_padrao, {
                    ram: data.ram,
                    sugerido: data.contexto_sugerido,
                    ajustarSelect: true,
                });
                aplicarPullDoStatus(data);
                return true;
            }
            if (aplicarPullDoStatus(data)) {
                mostrarGate('Escolha um modelo',
                    `Download em andamento. Aguarde terminar.`,
                    { presets: true, presetsData: data.presets }
                );
                return false;
            }
            esconderGate();
            atualizarSeletorModelo(data.presets);
            atualizarSeletorContexto(data.contextos, data.contexto_sugerido || data.contexto_padrao, {
                ram: data.ram,
                sugerido: data.contexto_sugerido,
                ajustarSelect: true,
            });
            return true;
        } catch (err) {
            setStatus('erro', 'Erro ao verificar');
            mostrarGate('Erro', 'Falha ao consultar status do Ollama.', {});
            return false;
        }
    }

    function mostrarGate(titulo, msgHtml, opcoes) {
        gate.classList.remove('d-none');
        chat.classList.add('d-none');
        gateTitulo.textContent = titulo;
        gateMsg.innerHTML = msgHtml;
        modoGerenciar = !!opcoes.gerenciar;
        btnInstalar.classList.toggle('d-none', !opcoes.instalar);
        btnIniciar.classList.toggle('d-none', !opcoes.iniciar);
        if (btnVoltar) btnVoltar.classList.toggle('d-none', !opcoes.voltar);
        if (opcoes.presets) {
            renderPresets(opcoes.presetsData || [], !!opcoes.gerenciar);
            presetsWrap.classList.remove('d-none');
        } else {
            presetsWrap.classList.add('d-none');
            presetsWrap.innerHTML = '';
        }
    }

    function renderPresets(presets, gerenciar) {
        const focos = (ultimoStatus && ultimoStatus.focos) || [];
        const ordem = focos.length
            ? focos.map(f => f.id)
            : [...new Set(presets.map(p => p.foco || 'geral'))];

        const mapaFoco = {};
        focos.forEach(f => { mapaFoco[f.id] = f; });
        const puxando = slugPuxando();

        let html = '';
        for (const focoId of ordem) {
            const grupo = presets.filter(p => (p.foco || 'geral') === focoId);
            if (!grupo.length) continue;
            const meta = mapaFoco[focoId] || { nome: focoId, icone: 'bi-collection', descricao: '' };
            html += `
                <div class="col-12">
                    <div class="ai-foco">
                        <div class="ai-foco__head">
                            <i class="bi ${escapeHtml(meta.icone)}"></i>
                            <div>
                                <div class="ai-foco__nome">${escapeHtml(meta.nome)}</div>
                                <div class="ai-foco__desc">${escapeHtml(meta.descricao || '')}</div>
                            </div>
                        </div>
                        <div class="row g-3">
                            ${grupo.map((p) => `
                                <div class="col-12 col-sm-6 col-lg-4">
                                    <div class="ai-preset ${p.baixado ? 'ai-preset--baixado' : ''}">
                                        <div class="ai-preset__head">
                                            <i class="bi ${p.icone} fs-4 text-primary"></i>
                                            <span class="ai-preset__nome">${escapeHtml(p.nome)}</span>
                                            <span class="ai-preset__tamanho">${escapeHtml(p.tamanho)}</span>
                                        </div>
                                        <div class="ai-preset__desc">${escapeHtml(p.descricao)}</div>
                                        <div class="ai-preset__slug">${escapeHtml(p.slug)}</div>
                                        ${p.baixado
                                            ? `<div class="ai-preset__acoes">
                                                   <span class="badge text-bg-success"><i class="bi bi-check2"></i> Baixado</span>
                                                   ${gerenciar ? `<button class="btn btn-sm btn-outline-danger" data-deletar="${escapeHtml(p.slug)}" title="Remover modelo">
                                                       <i class="bi bi-trash3"></i> Remover
                                                   </button>` : ''}
                                               </div>`
                                            : (puxando === p.slug
                                                ? `<button class="btn btn-sm btn-primary w-100" data-baixar="${escapeHtml(p.slug)}" disabled>
                                                       <span class="spinner-border spinner-border-sm me-1"></span> Baixando...
                                                   </button>`
                                                : `<button class="btn btn-sm btn-primary w-100" data-baixar="${escapeHtml(p.slug)}" ${puxando ? 'disabled' : ''}>
                                                       <i class="bi bi-download me-1"></i> Baixar
                                                   </button>`)
                                        }
                                    </div>
                                </div>
                            `).join('')}
                        </div>
                    </div>
                </div>
            `;
        }
        presetsWrap.innerHTML = html;
    }

    function atualizarSeletorModelo(presets) {
        const baixados = (presets || []).filter(p => p.baixado);
        if (!baixados.length) {
            modeloSelect.innerHTML = '';
            return;
        }
        const focos = (ultimoStatus && ultimoStatus.focos) || [];
        const ordem = focos.length
            ? focos.map(f => f.id)
            : [...new Set(baixados.map(p => p.foco || 'geral'))];
        const mapaFoco = {};
        focos.forEach(f => { mapaFoco[f.id] = f; });

        const salvo = localStorage.getItem(LS_MODELO);
        let html = '';
        for (const focoId of ordem) {
            const grupo = baixados.filter(p => (p.foco || 'geral') === focoId);
            if (!grupo.length) continue;
            const label = (mapaFoco[focoId] && mapaFoco[focoId].nome) || focoId;
            html += `<optgroup label="${escapeHtml(label)}">`;
            html += grupo.map(p =>
                `<option value="${escapeHtml(p.slug)}">${escapeHtml(p.nome)}</option>`
            ).join('');
            html += `</optgroup>`;
        }
        modeloSelect.innerHTML = html;
        const valido = baixados.find(p => p.slug === salvo);
        modeloSelect.value = valido ? salvo : baixados[0].slug;
        localStorage.setItem(LS_MODELO, modeloSelect.value);
    }

    function atualizarSeletorContexto(contextos, padrao, opts) {
        if (!ctxSelect) return;
        const opcoes = opts || {};
        const ram = opcoes.ram || (ultimoStatus && ultimoStatus.ram) || null;
        const lista = contextos && contextos.length
            ? contextos
            : [{ tokens: CTX_PADRAO, label: '16k', nome: 'Codigo diario', indicado: false, ram: '', ram_gb: 0 }];
        const sugerido = opcoes.sugerido
            || (lista.find((c) => c.indicado) || {}).tokens
            || padrao
            || CTX_PADRAO;
        const valorAtual = parseInt(ctxSelect.value || '', 10);
        const salvo = parseInt(localStorage.getItem(LS_CTX) || '', 10);
        const ajustar = !!opcoes.ajustarSelect;

        ctxSelect.innerHTML = lista.map((c) => {
            const tip = c.descricao || '';
            const texto = rotuloContexto(c, sugerido);
            return `<option value="${c.tokens}" title="${escapeHtml(tip)}">${escapeHtml(texto)}</option>`;
        }).join('');

        let escolhido = null;
        if (ajustar) {
            const salvoOk = lista.find((c) => c.tokens === salvo);
            if (salvoOk && !contextoExcedeMemoria(salvoOk)) {
                escolhido = salvo;
            } else {
                escolhido = sugerido;
            }
        } else if (lista.some((c) => c.tokens === valorAtual)) {
            escolhido = valorAtual;
        } else if (lista.some((c) => c.tokens === salvo)) {
            escolhido = salvo;
        } else {
            escolhido = sugerido;
        }

        ctxSelect.value = String(escolhido);
        if (ajustar) localStorage.setItem(LS_CTX, ctxSelect.value);
        atualizarRam(ram, {
            contextos: lista,
            tokens: escolhido,
            vram: (ultimoStatus && ultimoStatus.vram) || null,
        });
    }

    function modeloAtual() {
        return modeloSelect && modeloSelect.value
            ? modeloSelect.value
            : (localStorage.getItem(LS_MODELO) || 'qwen2.5-coder:3b');
    }

    function contextoAtual() {
        const v = parseInt(ctxSelect && ctxSelect.value ? ctxSelect.value : (localStorage.getItem(LS_CTX) || CTX_PADRAO), 10);
        return Number.isFinite(v) ? v : CTX_PADRAO;
    }

    if (modeloSelect) {
        modeloSelect.addEventListener('change', () => {
            localStorage.setItem(LS_MODELO, modeloSelect.value);
            verificarStatus();
        });
    }

    if (ctxSelect) {
        ctxSelect.addEventListener('change', () => {
            localStorage.setItem(LS_CTX, ctxSelect.value);
            const ram = ultimoStatus && ultimoStatus.ram;
            const lista = (ultimoStatus && ultimoStatus.contextos) || [];
            atualizarRam(ram, {
                contextos: lista,
                tokens: parseInt(ctxSelect.value, 10),
                vram: (ultimoStatus && ultimoStatus.vram) || null,
            });
        });
    }

    if (btnCtxInfo && ctxInfo) {
        btnCtxInfo.addEventListener('click', () => {
            ctxInfo.classList.toggle('d-none');
        });
    }
    if (btnCtxFechar && ctxInfo) {
        btnCtxFechar.addEventListener('click', () => {
            ctxInfo.classList.add('d-none');
        });
    }

    presetsWrap.addEventListener('click', async (e) => {
        const btnBaixar = e.target.closest('[data-baixar]');
        if (btnBaixar) {
            baixarModelo(btnBaixar.dataset.baixar, btnBaixar);
            return;
        }
        const btnDeletar = e.target.closest('[data-deletar]');
        if (btnDeletar) {
            await deletarModelo(btnDeletar.dataset.deletar, btnDeletar);
        }
    });

    if (btnGerenciar) {
        btnGerenciar.addEventListener('click', async () => {
            await verificarStatus();
            if (!ultimoStatus || !ultimoStatus.ollama_ativo) return;
            mostrarGate('Configurar modelos',
                'Baixe novos modelos ou remova os que nao usa mais para liberar espaco.',
                { presets: true, presetsData: ultimoStatus.presets, gerenciar: true, voltar: true }
            );
        });
    }

    if (btnVoltar) {
        btnVoltar.addEventListener('click', async () => {
            const ok = await verificarStatus();
            if (ok) esconderGate();
        });
    }

    async function deletarModelo(slug, btn) {
        if (!confirm(`Remover o modelo "${slug}" do disco?\nIsso libera espaco, mas sera necessario baixar de novo para usar.`)) {
            return;
        }
        if (btn) btn.disabled = true;
        gateErro.classList.add('d-none');
        try {
            const resp = await fetch('/api/ai/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ modelo: slug }),
            });
            const data = await resp.json();
            if (!resp.ok || !data.ok) throw new Error(data.msg || ('HTTP ' + resp.status));

            if (localStorage.getItem(LS_MODELO) === slug) {
                localStorage.removeItem(LS_MODELO);
            }

            await verificarStatus();
        } catch (err) {
            exibirErro(err.message);
            if (btn) btn.disabled = false;
        }
    }

    function esconderGate() {
        modoGerenciar = false;
        gate.classList.add('d-none');
        chat.classList.remove('d-none');
        carregarChats();
    }

    async function consumirStream(url, { onEvent, headers, body } = {}) {
        const init = { method: 'POST' };
        if (headers) init.headers = headers;
        if (body) init.body = body;
        const resp = await fetch(url, init);
        if (!resp.ok || !resp.body) {
            const txt = await resp.text();
            throw new Error(txt || ('HTTP ' + resp.status));
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        const onEv = onEvent || (() => {});
        const processar = (linha) => {
            if (!linha.trim()) return;
            let ev;
            try { ev = JSON.parse(linha); } catch (_) { return; }
            onEv(ev);
        };
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const linhas = buffer.split('\n');
            buffer = linhas.pop() || '';
            for (const linha of linhas) processar(linha);
        }
        buffer += decoder.decode();
        if (buffer.trim()) processar(buffer);
    }

    function slugPuxando() {
        const p = ultimoStatus && ultimoStatus.pull;
        if (p && p.ativo && p.modelo) return p.modelo;
        return pullSlugLocal || '';
    }

    function aplicarPullDoStatus(st) {
        const p = (st && st.pull) || {};
        if (p.ativo) {
            pullSlugLocal = p.modelo || pullSlugLocal;
            prepararPullUI(p.status || `Baixando ${p.modelo || ''}...`);
            atualizarProgresso(p);
            if (presetsWrap && !presetsWrap.classList.contains('d-none')) {
                renderPresets((st && st.presets) || [], !!modoGerenciar);
            }
            return true;
        }
        if (p.erro && pullSlugLocal) {
            exibirErro(p.erro);
        }
        return false;
    }

    function prepararPullUI(textoInicial) {
        pullWrap.classList.remove('d-none');
        gateErro.classList.add('d-none');
        pullBar.style.width = '0%';
        pullPercent.textContent = '0%';
        pullStatus.textContent = textoInicial;
        pullDetalhe.textContent = '';
        try { pullWrap.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); } catch (_) {}
    }

    function exibirErro(msg) {
        gateErro.textContent = 'Erro: ' + msg;
        gateErro.classList.remove('d-none');
    }

    async function baixarModelo(slug, btn) {
        if (slugPuxando() && slugPuxando() !== slug) return;
        pullSlugLocal = slug;
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Baixando...';
        }
        prepararPullUI(`Baixando ${slug}...`);
        if (ultimoStatus && ultimoStatus.presets) {
            renderPresets(ultimoStatus.presets, !!modoGerenciar);
        }
        try {
            await consumirStream('/api/ai/pull', {
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ modelo: slug }),
                onEvent: (ev) => {
                    if (ev.erro) throw new Error(ev.status || ev.detalhe || 'Erro no pull');
                    atualizarProgresso(ev);
                },
            });
            pullStatus.textContent = 'Download concluido';
            pullBar.style.width = '100%';
            pullPercent.textContent = '100%';
            localStorage.setItem(LS_MODELO, slug);
            pullSlugLocal = '';
            setTimeout(verificarStatus, 600);
        } catch (err) {
            exibirErro(err.message);
            pullSlugLocal = '';
            if (btn) btn.disabled = false;
            if (ultimoStatus && ultimoStatus.presets) {
                renderPresets(ultimoStatus.presets, !!modoGerenciar);
            }
        }
    }

    btnInstalar.addEventListener('click', async () => {
        btnInstalar.disabled = true;
        prepararPullUI('Preparando instalacao do Ollama...');
        pullBar.classList.add('progress-bar-animated', 'progress-bar-striped');
        let concluido = false;
        try {
            await consumirStream('/api/ai/instalar-ollama', {
                onEvent: (ev) => {
                    if (ev.erro) {
                        const det = ev.detalhe ? ` (${ev.detalhe})` : '';
                        throw new Error((ev.status || 'Falha na instalacao') + det);
                    }
                    if (ev.etapa === 'download') {
                        pullBar.classList.remove('progress-bar-animated', 'progress-bar-striped');
                        atualizarProgresso(ev);
                    } else if (ev.etapa === 'instalando') {
                        if (typeof ev.completed === 'number' && ev.total) {
                            pullBar.classList.remove('progress-bar-animated', 'progress-bar-striped');
                            atualizarProgresso(ev);
                        } else {
                            pullBar.classList.add('progress-bar-animated', 'progress-bar-striped');
                            pullBar.style.width = '100%';
                            pullPercent.textContent = '';
                        }
                        pullStatus.textContent = ev.status || 'Instalando...';
                        pullDetalhe.textContent = (ultimoStatus && ultimoStatus.sistema === 'Linux')
                            ? 'Instalando no servidor do hub. Pode levar alguns minutos.'
                            : 'Acompanhe o instalador do Ollama na sua tela.';
                    } else if (ev.etapa === 'concluido') {
                        concluido = true;
                        pullBar.classList.remove('progress-bar-animated', 'progress-bar-striped');
                        pullBar.style.width = '100%';
                        pullPercent.textContent = '100%';
                        pullStatus.textContent = ev.status || 'Ollama instalado!';
                        pullDetalhe.textContent = 'Abrindo escolha de modelos...';
                    }
                },
            });
            if (!concluido) {
                pullBar.classList.remove('progress-bar-animated', 'progress-bar-striped');
                pullBar.style.width = '100%';
                pullPercent.textContent = '100%';
                pullStatus.textContent = 'Instalacao concluida';
                pullDetalhe.textContent = 'Verificando Ollama...';
            }
            await verificarStatus();
        } catch (err) {
            pullBar.classList.remove('progress-bar-animated', 'progress-bar-striped');
            exibirErro(err.message);
            btnInstalar.disabled = false;
        }
    });

    async function aplicarStatusPronto(st) {
        ultimoStatus = st;
        atualizarRam(st.ram, { vram: st.vram });
        pullWrap.classList.add('d-none');
        const algumBaixado = (st.presets || []).some(p => p.baixado);
        if (!algumBaixado) {
            setStatus('warn', 'Nenhum modelo');
            mostrarGate('Escolha um modelo',
                'Nenhum modelo foi baixado ainda. Selecione abaixo qual instalar.',
                { presets: true, presetsData: st.presets }
            );
            return false;
        }
        setStatus('ok', 'Pronto');
        atualizarSeletorModelo(st.presets);
        atualizarSeletorContexto(st.contextos, st.contexto_sugerido || st.contexto_padrao, {
            ram: st.ram,
            sugerido: st.contexto_sugerido,
            ajustarSelect: true,
        });
        esconderGate();
        return true;
    }

    btnIniciar.addEventListener('click', async () => {
        btnIniciar.disabled = true;
        gateErro.classList.add('d-none');
        try {
            const resp = await fetch('/api/ai/iniciar-ollama', { method: 'POST' });
            const data = await resp.json();
            if (!resp.ok || !data.ok) throw new Error(data.msg || ('HTTP ' + resp.status));
            pullWrap.classList.remove('d-none');
            pullDetalhe.textContent = 'O app do Ollama pode abrir em segundo plano.';
            pullBar.style.width = '100%';
            pullPercent.textContent = '';

            const maxTentativas = 60;
            for (let i = 1; i <= maxTentativas; i++) {
                pullStatus.textContent = `Aguardando Ollama iniciar... (${i}/${maxTentativas})`;
                await new Promise(r => setTimeout(r, 1000));
                let st;
                try {
                    const respSt = await fetch(urlStatus());
                    st = await respSt.json();
                } catch (_) {
                    continue;
                }
                if (!st.ollama_ativo) continue;
                btnIniciar.disabled = false;
                await aplicarStatusPronto(st);
                return;
            }
            throw new Error('Ollama nao respondeu a tempo. Abra o app Ollama e tente novamente.');
        } catch (err) {
            exibirErro(err.message);
            btnIniciar.disabled = false;
        }
    });

    function atualizarProgresso(ev) {
        const status = ev.status || '';
        pullStatus.textContent = status;
        if (ev.total && typeof ev.completed === 'number') {
            const pct = Math.min(100, (ev.completed / ev.total) * 100);
            pullBar.style.width = pct.toFixed(1) + '%';
            pullPercent.textContent = pct.toFixed(1) + '%';
            pullDetalhe.textContent = `${formatBytes(ev.completed)} / ${formatBytes(ev.total)}`;
        } else if (status.toLowerCase().includes('success')) {
            pullBar.style.width = '100%';
            pullPercent.textContent = '100%';
        }
    }

    function soUmaNovaConversa() {
        if (chatsCache.length !== 1) return false;
        const c = chatsCache[0];
        return c.titulo === 'Nova conversa' || !c.total_mensagens;
    }

    function atualizarVisibilidadeExcluir() {
        if (!btnExcluir) return;
        if (chatAtual && !soUmaNovaConversa()) {
            btnExcluir.classList.remove('d-none');
        } else {
            btnExcluir.classList.add('d-none');
        }
    }

    async function carregarChats() {
        try {
            const resp = await fetch('/api/ai/chats');
            const data = await resp.json();
            const chats = data.chats || [];
            chatsCache = chats;
            renderListaChats(chats);
            await garantirConversaAtiva(chats);
            atualizarVisibilidadeExcluir();
        } catch (err) {
            listaChats.innerHTML = `<div class="text-danger small">Erro ao carregar</div>`;
        }
    }

    async function criarNovaConversa() {
        const resp = await fetch('/api/ai/chats', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ titulo: 'Nova conversa' }),
        });
        const data = await resp.json();
        await abrirChat(data.chat.id);
        const listaResp = await fetch('/api/ai/chats');
        const listaData = await listaResp.json();
        chatsCache = listaData.chats || [];
        renderListaChats(chatsCache);
        atualizarVisibilidadeExcluir();
    }

    async function garantirConversaAtiva(chats) {
        if (chatAtual) return;
        const lista = chats || [];
        if (!lista.length) {
            await criarNovaConversa();
            return;
        }
        // Lista ja vem por atualizado_em DESC — abre a conversa mais recente.
        await abrirChat(lista[0].id);
    }

    function renderListaChats(chats) {
        if (!chats.length) {
            listaChats.innerHTML = `<div class="text-secondary small text-center py-3">Sem conversas ainda.</div>`;
            return;
        }
        const ocultarExcluir = soUmaNovaConversa();
        listaChats.innerHTML = chats.map((c) => `
            <div class="ai-chat__item ${chatAtual && chatAtual.id === c.id ? 'ai-chat__item--ativo' : ''}" data-id="${c.id}">
                <span class="ai-chat__item-titulo" title="${escapeHtml(c.titulo)}">${escapeHtml(c.titulo)}</span>
                ${ocultarExcluir ? '' : `
                <button class="ai-chat__item-acao" data-acao="excluir" data-id="${c.id}" title="Excluir">
                    <i class="bi bi-x-lg"></i>
                </button>`}
            </div>
        `).join('');
    }

    listaChats.addEventListener('click', async (e) => {
        const btnAcao = e.target.closest('[data-acao="excluir"]');
        if (btnAcao) {
            e.stopPropagation();
            const id = parseInt(btnAcao.dataset.id, 10);
            if (!confirm('Excluir esta conversa?')) return;
            await fetch(`/api/ai/chats/${id}`, { method: 'DELETE' });
            if (chatAtual && chatAtual.id === id) {
                chatAtual = null;
            }
            carregarChats();
            return;
        }
        const item = e.target.closest('.ai-chat__item');
        if (item) {
            const id = parseInt(item.dataset.id, 10);
            abrirChat(id);
        }
    });

    btnNovoChat.addEventListener('click', async () => {
        await criarNovaConversa();
    });

    btnRenomear.addEventListener('click', async () => {
        if (!chatAtual) return;
        const novo = prompt('Novo titulo:', chatAtual.titulo);
        if (!novo || !novo.trim()) return;
        const resp = await fetch(`/api/ai/chats/${chatAtual.id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ titulo: novo.trim() }),
        });
        const data = await resp.json();
        chatAtual = data.chat;
        tituloEl.textContent = chatAtual.titulo;
        carregarChats();
    });

    btnExcluir.addEventListener('click', async () => {
        if (!chatAtual) return;
        if (!confirm('Excluir esta conversa?')) return;
        await fetch(`/api/ai/chats/${chatAtual.id}`, { method: 'DELETE' });
        chatAtual = null;
        carregarChats();
    });

    async function abrirChat(id) {
        try {
            const resp = await fetch(`/api/ai/chats/${id}`);
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            const data = await resp.json();
            chatAtual = data.chat;
            tituloEl.textContent = chatAtual.titulo;
            btnRenomear.classList.remove('d-none');
            atualizarVisibilidadeExcluir();
            input.disabled = false;
            btnEnviar.disabled = false;
            mensagensEl.innerHTML = '';
            (data.mensagens || []).forEach((m) => adicionarMensagem(m.role, m.conteudo, m));
            if (!data.mensagens || !data.mensagens.length) {
                mensagensEl.innerHTML = `
                    <div class="ai-chat__empty text-secondary text-center py-5">
                        <i class="bi bi-chat-square-dots display-6 d-block mb-2"></i>
                        Envie sua primeira mensagem.
                    </div>`;
            }
            atualizarBotoesEditar();
            oferecerReenvioSePendente(data.mensagens || []);
            renderListaChatsAtiva();
            input.focus();
        } catch (err) {
            alert('Erro ao abrir conversa: ' + err.message);
        }
    }

    function renderListaChatsAtiva() {
        listaChats.querySelectorAll('.ai-chat__item').forEach((el) => {
            const id = parseInt(el.dataset.id, 10);
            el.classList.toggle('ai-chat__item--ativo', chatAtual && chatAtual.id === id);
        });
    }

    function resetarPainelMensagens() {
        tituloEl.textContent = 'Nova conversa';
        btnRenomear.classList.add('d-none');
        btnExcluir.classList.add('d-none');
        input.disabled = false;
        btnEnviar.disabled = false;
        mensagensEl.innerHTML = `
            <div class="ai-chat__empty text-secondary text-center py-5">
                <i class="bi bi-chat-square-dots display-6 d-block mb-2"></i>
                Envie sua primeira mensagem.
            </div>`;
    }

    function adicionarMensagem(role, conteudo, meta) {
        const vazio = mensagensEl.querySelector('.ai-chat__empty');
        if (vazio) vazio.remove();

        const wrap = document.createElement('div');
        wrap.className = `ai-chat__msg ai-chat__msg--${role}`;
        if (meta && meta.id != null) wrap.dataset.id = String(meta.id);
        wrap.dataset.conteudo = conteudo || '';
        wrap.innerHTML = `
            <span class="ai-chat__msg-role">${role === 'user' ? 'Voce' : 'Assistente'}</span>
            <div class="ai-chat__msg-corpo"></div>
            <span class="ai-chat__msg-meta d-none"></span>
        `;
        const corpo = wrap.querySelector('.ai-chat__msg-corpo');
        renderMarkdown(corpo, conteudo);
        if (role === 'user') {
            const acoes = document.createElement('div');
            acoes.className = 'ai-chat__msg-acoes d-none';
            acoes.innerHTML = `
                <button type="button" class="btn btn-sm btn-outline-secondary ai-chat__btn-editar" title="Editar e reenviar">
                    <i class="bi bi-pencil"></i> Editar
                </button>
            `;
            wrap.appendChild(acoes);
        }
        mensagensEl.appendChild(wrap);
        rolarFinal();
        return wrap;
    }

    function atualizarBotoesEditar() {
        const users = mensagensEl.querySelectorAll('.ai-chat__msg--user');
        users.forEach((el, idx) => {
            const acoes = el.querySelector('.ai-chat__msg-acoes');
            if (!acoes) return;
            // Editar só a última pergunta do usuário (estilo ChatGPT)
            acoes.classList.toggle('d-none', enviando || idx !== users.length - 1 || !el.dataset.id);
        });
    }

    function setEnviandoUI(ativo) {
        enviando = !!ativo;
        if (btnEnviar) btnEnviar.classList.toggle('d-none', enviando);
        if (btnParar) btnParar.classList.toggle('d-none', !enviando);
        if (btnAnexo) btnAnexo.disabled = enviando;
        input.disabled = enviando;
        atualizarBotoesEditar();
    }

    function exibirMetricas(wrap, m) {
        if (!wrap || !m) return;
        const meta = wrap.querySelector('.ai-chat__msg-meta');
        if (!meta) return;
        const partes = [];
        if (m.total_s != null) partes.push(`${m.total_s}s`);
        if (m.tokens) partes.push(`${m.tokens} tok`);
        if (m.tokens_por_s != null) partes.push(`${m.tokens_por_s} tok/s`);
        if (m.load_s && m.load_s > 0.5) partes.push(`load ${m.load_s}s`);
        if (!partes.length) return;
        meta.textContent = partes.join(' · ');
        meta.classList.remove('d-none');
    }

    function renderMarkdown(el, conteudo) {
        el.innerHTML = marked.parse(conteudo || '');
        el.querySelectorAll('pre').forEach((pre) => {
            pre.classList.add('ai-chat__codeblock');
            if (pre.querySelector('.ai-chat__copy')) return;
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'ai-chat__copy';
            btn.innerHTML = '<i class="bi bi-clipboard"></i> Copiar';
            btn.addEventListener('click', async () => {
                const code = pre.querySelector('code');
                const texto = code ? code.innerText : pre.innerText;
                try {
                    await navigator.clipboard.writeText(texto);
                    btn.classList.add('ai-chat__copy--ok');
                    btn.innerHTML = '<i class="bi bi-check2"></i> Copiado';
                    setTimeout(() => {
                        btn.classList.remove('ai-chat__copy--ok');
                        btn.innerHTML = '<i class="bi bi-clipboard"></i> Copiar';
                    }, 1500);
                } catch (_) {
                    btn.textContent = 'Erro';
                }
            });
            pre.appendChild(btn);
        });
    }

    function rolarFinal() {
        mensagensEl.scrollTop = mensagensEl.scrollHeight;
    }

    function renderAnexos() {
        if (!anexosEl) return;
        if (!anexosPendentes.length) {
            anexosEl.classList.add('d-none');
            anexosEl.innerHTML = '';
            return;
        }
        anexosEl.classList.remove('d-none');
        anexosEl.innerHTML = anexosPendentes.map((f, i) => `
            <span class="ai-chat__anexo-chip" data-idx="${i}">
                <i class="bi bi-paperclip"></i>
                <span title="${escapeHtml(f.name)}">${escapeHtml(f.name)}</span>
                <button type="button" data-remover-anexo="${i}" title="Remover">&times;</button>
            </span>
        `).join('');
    }

    function adicionarAnexos(lista) {
        for (const f of lista) {
            if (anexosPendentes.length >= MAX_ANEXOS) break;
            if (anexosPendentes.some((x) => x.name === f.name && x.size === f.size)) continue;
            anexosPendentes.push(f);
        }
        renderAnexos();
    }

    if (btnAnexo && fileInput) {
        btnAnexo.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', () => {
            adicionarAnexos(Array.from(fileInput.files || []));
            fileInput.value = '';
        });
    }

    if (anexosEl) {
        anexosEl.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-remover-anexo]');
            if (!btn) return;
            const idx = Number(btn.dataset.removerAnexo);
            anexosPendentes.splice(idx, 1);
            renderAnexos();
        });
    }

    input.addEventListener('paste', (e) => {
        const items = e.clipboardData && e.clipboardData.files;
        if (items && items.length) {
            adicionarAnexos(Array.from(items));
        }
    });

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (enviando || !chatAtual) return;
        const texto = input.value.trim();
        if (!texto && !anexosPendentes.length) return;

        if (envioAbort) {
            try { envioAbort.abort(); } catch (_) { /* ignore */ }
        }
        envioAbort = new AbortController();
        setEnviandoUI(true);

        const filesEnvio = anexosPendentes.slice();
        const textoEnvio = texto;
        input.value = '';
        anexosPendentes = [];
        renderAnexos();

        const preview = textoEnvio || filesEnvio.map((f) => '📎 ' + f.name).join('\n');
        const wrapUser = adicionarMensagem('user', preview);
        wrapUser.dataset.conteudo = textoEnvio;
        const wrapAssistente = adicionarMensagem('assistant', '');
        const corpoAssistente = wrapAssistente.querySelector('.ai-chat__msg-corpo');
        const cursor = document.createElement('span');
        cursor.className = 'ai-chat__cursor';
        corpoAssistente.appendChild(cursor);

        let acumulado = '';
        let paradoPeloUsuario = false;

        try {
            const fd = new FormData();
            fd.append('conteudo', textoEnvio);
            fd.append('modelo', modeloAtual());
            fd.append('num_ctx', String(contextoAtual()));
            filesEnvio.forEach((f) => fd.append('arquivos', f, f.name));

            const resp = await fetch(`/api/ai/chats/${chatAtual.id}/mensagens`, {
                method: 'POST',
                body: fd,
                signal: envioAbort.signal,
            });
            if (!resp.ok || !resp.body) {
                const txt = await resp.text();
                throw new Error(txt || ('HTTP ' + resp.status));
            }

            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const linhas = buffer.split('\n');
                buffer = linhas.pop();
                for (const linha of linhas) {
                    if (!linha.trim()) continue;
                    let ev;
                    try { ev = JSON.parse(linha); } catch (_) { continue; }

                    if (ev.tipo === 'user_msg' && ev.mensagem && ev.mensagem.id != null) {
                        wrapUser.dataset.id = String(ev.mensagem.id);
                        if (ev.mensagem.conteudo) wrapUser.dataset.conteudo = ev.mensagem.conteudo;
                        atualizarBotoesEditar();
                    } else if (ev.tipo === 'delta') {
                        acumulado += ev.conteudo;
                        renderMarkdown(corpoAssistente, acumulado);
                        corpoAssistente.appendChild(cursor);
                        rolarFinal();
                    } else if (ev.tipo === 'aviso') {
                        const nota = document.createElement('div');
                        nota.className = 'ai-chat__aviso-ram small text-warning mb-2';
                        nota.innerHTML = `<i class="bi bi-exclamation-triangle me-1"></i>${escapeHtml(ev.msg || 'Contexto limitado pela RAM.')}`;
                        wrapAssistente.insertBefore(nota, corpoAssistente);
                    } else if (ev.tipo === 'erro') {
                        throw new Error(ev.msg || 'Erro do modelo');
                    } else if (ev.tipo === 'parado') {
                        paradoPeloUsuario = true;
                        throw new Error(ev.msg || 'Geracao interrompida pelo usuario.');
                    } else if (ev.tipo === 'fim') {
                        cursor.remove();
                        if (ev.mensagem && ev.mensagem.id != null) {
                            wrapAssistente.dataset.id = String(ev.mensagem.id);
                        }
                        renderMarkdown(corpoAssistente, acumulado);
                        exibirMetricas(wrapAssistente, ev.metricas);
                        rolarFinal();
                    }
                }
            }
        } catch (err) {
            cursor.remove();
            const abortado = (err && err.name === 'AbortError') || paradoPeloUsuario;
            if (acumulado) {
                renderMarkdown(corpoAssistente, acumulado);
                const errEl = document.createElement('div');
                errEl.className = 'text-warning small mt-2';
                errEl.textContent = abortado
                    ? 'Parado pelo usuario.'
                    : ('Interrompido: ' + (err.message || err));
                wrapAssistente.appendChild(errEl);
            } else if (abortado) {
                corpoAssistente.innerHTML = `<span class="text-secondary">Geracao cancelada.</span>`;
            } else {
                corpoAssistente.innerHTML = `
                    <span class="text-danger">Erro: ${escapeHtml(err.message || String(err))}</span>
                    <div class="ai-chat__reenviar ai-chat__reenviar--inline mt-2">
                        <button type="button" class="btn btn-sm btn-outline-primary ai-chat__reenviar-btn">
                            <i class="bi bi-arrow-repeat"></i> Reenviar
                        </button>
                    </div>`;
                const btnInline = corpoAssistente.querySelector('.ai-chat__reenviar-btn');
                if (btnInline) {
                    btnInline.addEventListener('click', () => {
                        if (enviando) return;
                        input.value = textoEnvio || '';
                        anexosPendentes = (filesEnvio && filesEnvio.length) ? filesEnvio.slice() : [];
                        renderAnexos();
                        form.requestSubmit();
                    });
                }
            }
            mostrarAcoesPosInterrupcao(wrapAssistente, textoEnvio, filesEnvio);
        } finally {
            envioAbort = null;
            setEnviandoUI(false);
            input.focus();
            carregarChats();
        }
    });

    function oferecerReenvioSePendente(msgs) {
        if (!msgs || !msgs.length || msgs[msgs.length - 1].role !== 'user') return;
        const texto = msgs[msgs.length - 1].conteudo || '';
        const wrapAssistente = adicionarMensagem('assistant', '');
        const corpo = wrapAssistente.querySelector('.ai-chat__msg-corpo');
        corpo.innerHTML = '<span class="text-secondary small">Sem resposta do assistente.</span>';
        mostrarAcoesPosInterrupcao(wrapAssistente, texto, []);
    }

    function mostrarAcoesPosInterrupcao(wrapAssistente, texto, files) {
        if (!wrapAssistente) return;
        wrapAssistente.querySelectorAll('.ai-chat__reenviar:not(.ai-chat__reenviar--inline)').forEach((el) => el.remove());
        const temInline = !!wrapAssistente.querySelector('.ai-chat__reenviar--inline');
        const bar = document.createElement('div');
        bar.className = 'ai-chat__reenviar';
        bar.innerHTML = `
            ${temInline ? '' : `
            <button type="button" class="btn btn-sm btn-primary ai-chat__reenviar-btn">
                <i class="bi bi-arrow-repeat"></i> Reenviar pergunta
            </button>`}
            <button type="button" class="btn btn-sm btn-outline-secondary ai-chat__editar-btn">
                <i class="bi bi-pencil"></i> Editar pergunta
            </button>
        `;
        const btnReenviar = bar.querySelector('.ai-chat__reenviar-btn');
        if (btnReenviar) {
            btnReenviar.addEventListener('click', () => {
                if (enviando) return;
                input.value = texto || '';
                anexosPendentes = (files && files.length) ? files.slice() : [];
                renderAnexos();
                form.requestSubmit();
            });
        }
        bar.querySelector('.ai-chat__editar-btn').addEventListener('click', async () => {
            if (enviando) return;
            const lastUser = [...mensagensEl.querySelectorAll('.ai-chat__msg--user')].pop();
            if (lastUser) await editarPergunta(lastUser, texto);
            else {
                input.value = texto || '';
                input.focus();
            }
        });
        wrapAssistente.appendChild(bar);
        rolarFinal();
    }

    async function editarPergunta(wrapUser, textoOverride) {
        if (enviando || !chatAtual || !wrapUser) return;
        const msgId = wrapUser.dataset.id;
        const texto = textoOverride != null ? textoOverride : (wrapUser.dataset.conteudo || '');
        if (!msgId) {
            input.value = texto;
            input.focus();
            return;
        }
        try {
            const resp = await fetch(`/api/ai/chats/${chatAtual.id}/mensagens/${msgId}`, {
                method: 'DELETE',
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(data.detail || 'Falha ao editar');

            // Remove essa msg e tudo depois no DOM
            let el = wrapUser;
            while (el) {
                const next = el.nextElementSibling;
                el.remove();
                el = next;
            }
            input.value = texto;
            anexosPendentes = [];
            renderAnexos();
            atualizarBotoesEditar();
            input.focus();
        } catch (err) {
            alert('Erro ao editar: ' + err.message);
        }
    }

    mensagensEl.addEventListener('click', (e) => {
        const btn = e.target.closest('.ai-chat__btn-editar');
        if (!btn) return;
        const wrapUser = btn.closest('.ai-chat__msg--user');
        if (wrapUser) editarPergunta(wrapUser);
    });

    function descarregarModeloBeacon(modelo) {
        // modelo vazio = descarrega todos os que estiverem na RAM (ver API)
        const body = JSON.stringify({ modelo: modelo || '' });
        try {
            if (navigator.sendBeacon) {
                const blob = new Blob([body], { type: 'application/json' });
                if (navigator.sendBeacon('/api/ai/descarregar', blob)) return;
            }
        } catch (_) { /* ignore */ }
        fetch('/api/ai/descarregar', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body,
            keepalive: true,
        }).catch(() => {});
    }

    async function liberarMemoriaOllama(opts) {
        const silencioso = !!(opts && opts.silencioso);
        if (btnLiberarMem) btnLiberarMem.disabled = true;
        try {
            const resp = await fetch('/api/ai/descarregar', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ modelo: '' }),
            });
            const data = await resp.json().catch(() => ({}));
            if (!silencioso) {
                if (resp.ok && data.ok) {
                    setStatus('ok', data.msg || 'Memoria liberada');
                } else {
                    setStatus('warn', (data && data.msg) || 'Falha ao liberar');
                }
            }
            setTimeout(verificarStatus, 400);
            return !!(resp.ok && data.ok);
        } catch (_) {
            if (!silencioso) setStatus('erro', 'Falha ao liberar');
            return false;
        } finally {
            if (btnLiberarMem) btnLiberarMem.disabled = false;
        }
    }

    if (btnLiberarMem) {
        btnLiberarMem.addEventListener('click', () => liberarMemoriaOllama());
    }

    if (btnParar) {
        btnParar.addEventListener('click', () => {
            if (!enviando || !envioAbort) return;
            envioAbort.abort();
            descarregarModeloBeacon('');
        });
    }

    window.addEventListener('pagehide', () => {
        if (enviando && envioAbort) {
            try { envioAbort.abort(); } catch (_) { /* ignore */ }
        }
        // Sempre libera ao sair do chat — keep_alive do Ollama nao deve segurar 15GB
        descarregarModeloBeacon('');
    });

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            form.requestSubmit();
        }
    });

    verificarStatus();
    setInterval(() => {
        if (document.hidden) return;
        fetch(urlStatus())
            .then((r) => r.json())
            .then((data) => {
                if (ultimoStatus) {
                    ultimoStatus.ram = data.ram;
                    ultimoStatus.vram = data.vram;
                    ultimoStatus.memoria_modo = data.memoria_modo;
                    ultimoStatus.contexto_sugerido = data.contexto_sugerido;
                    if (data.contextos) ultimoStatus.contextos = data.contextos;
                    if (data.ram_folga_bytes) ultimoStatus.ram_folga_bytes = data.ram_folga_bytes;
                    if (data.vram_folga_bytes) ultimoStatus.vram_folga_bytes = data.vram_folga_bytes;
                    if (typeof data.modelo_cabe === 'boolean') ultimoStatus.modelo_cabe = data.modelo_cabe;
                    if (data.modelo_ram_estimada_gb != null) {
                        ultimoStatus.modelo_ram_estimada_gb = data.modelo_ram_estimada_gb;
                    }
                    if (data.pull) ultimoStatus.pull = data.pull;
                }
                if (data.pull && data.pull.ativo) {
                    aplicarPullDoStatus(data);
                }
                // Atualiza labels/aviso sem forcar troca do select
                if (ctxSelect && !ctxSelect.classList.contains('d-none') && data.contextos) {
                    atualizarSeletorContexto(data.contextos, data.contexto_sugerido || data.contexto_padrao, {
                        ram: data.ram,
                        sugerido: data.contexto_sugerido,
                        ajustarSelect: false,
                    });
                } else {
                    atualizarRam(data.ram, { vram: data.vram });
                }
            })
            .catch(() => {});
    }, 10000);

    window.aiRecarregarAposLimpar = function () {
        chatAtual = null;
        resetarPainelMensagens();
        carregarChats();
    };
})();
