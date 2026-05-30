(function () {
    const statusBadge = document.getElementById('ai-status-badge');
    const gate = document.getElementById('ai-gate');
    const gateMsg = document.getElementById('ai-gate-msg');
    const gateTitulo = document.getElementById('ai-gate-titulo');
    const gateErro = document.getElementById('ai-gate-erro');
    const presetsWrap = document.getElementById('ai-presets');
    const btnInstalar = document.getElementById('ai-btn-instalar');
    const btnIniciar = document.getElementById('ai-btn-iniciar');
    const pullWrap = document.getElementById('ai-pull-wrap');
    const pullBar = document.getElementById('ai-pull-bar');
    const pullPercent = document.getElementById('ai-pull-percent');
    const pullStatus = document.getElementById('ai-pull-status');
    const pullDetalhe = document.getElementById('ai-pull-detalhe');

    const chat = document.getElementById('ai-chat');
    const listaChats = document.getElementById('ai-lista-chats');
    const btnNovoChat = document.getElementById('ai-novo-chat');
    const tituloEl = document.getElementById('ai-chat-titulo');
    const modeloSelect = document.getElementById('ai-modelo-select');
    const btnGerenciar = document.getElementById('ai-btn-gerenciar');
    const btnRenomear = document.getElementById('ai-btn-renomear');
    const btnExcluir = document.getElementById('ai-btn-excluir');
    const mensagensEl = document.getElementById('ai-mensagens');
    const form = document.getElementById('ai-form');
    const input = document.getElementById('ai-input');
    const btnEnviar = document.getElementById('ai-btn-enviar');

    const LS_MODELO = 'ai_chat_modelo';
    let chatAtual = null;
    let enviando = false;
    let ultimoStatus = null;

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

    async function verificarStatus() {
        try {
            const resp = await fetch('/api/ai/status');
            const data = await resp.json();
            ultimoStatus = data;

            if (!data.ollama_ativo) {
                setStatus('erro', 'Ollama offline');
                if (!data.ollama_instalado) {
                    if (data.sistema === 'Windows') {
                        mostrarGate('Ollama nao instalado',
                            `Ollama nao esta instalado neste computador.<br>
                             Clique para baixar e instalar automaticamente.`,
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
                return false;
            }

            setStatus('ok', 'Pronto');
            esconderGate();
            atualizarSeletorModelo(data.presets);
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
        btnInstalar.classList.toggle('d-none', !opcoes.instalar);
        btnIniciar.classList.toggle('d-none', !opcoes.iniciar);
        if (opcoes.presets) {
            renderPresets(opcoes.presetsData || []);
            presetsWrap.classList.remove('d-none');
        } else {
            presetsWrap.classList.add('d-none');
            presetsWrap.innerHTML = '';
        }
    }

    function renderPresets(presets) {
        presetsWrap.innerHTML = presets.map((p) => `
            <div class="col-12 col-md-4">
                <div class="ai-preset ${p.baixado ? 'ai-preset--baixado' : ''}">
                    <div class="ai-preset__head">
                        <i class="bi ${p.icone} fs-4 text-primary"></i>
                        <span class="ai-preset__nome">${escapeHtml(p.nome)}</span>
                        <span class="ai-preset__tamanho">${escapeHtml(p.tamanho)}</span>
                    </div>
                    <div class="ai-preset__desc">${escapeHtml(p.descricao)}</div>
                    <div class="ai-preset__slug">${escapeHtml(p.slug)}</div>
                    ${p.baixado
                        ? `<span class="badge text-bg-success ai-preset__badge"><i class="bi bi-check2"></i> Baixado</span>`
                        : `<button class="btn btn-sm btn-primary w-100" data-baixar="${escapeHtml(p.slug)}">
                               <i class="bi bi-download me-1"></i> Baixar
                           </button>`
                    }
                </div>
            </div>
        `).join('');
    }

    function atualizarSeletorModelo(presets) {
        const baixados = (presets || []).filter(p => p.baixado);
        if (!baixados.length) {
            modeloSelect.innerHTML = '';
            return;
        }
        const salvo = localStorage.getItem(LS_MODELO);
        modeloSelect.innerHTML = baixados.map(p =>
            `<option value="${escapeHtml(p.slug)}">${escapeHtml(p.nome)} (${escapeHtml(p.slug)})</option>`
        ).join('');
        const valido = baixados.find(p => p.slug === salvo);
        modeloSelect.value = valido ? salvo : baixados[0].slug;
        localStorage.setItem(LS_MODELO, modeloSelect.value);
    }

    function modeloAtual() {
        return modeloSelect && modeloSelect.value
            ? modeloSelect.value
            : (localStorage.getItem(LS_MODELO) || 'qwen2.5-coder:3b');
    }

    if (modeloSelect) {
        modeloSelect.addEventListener('change', () => {
            localStorage.setItem(LS_MODELO, modeloSelect.value);
        });
    }

    presetsWrap.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-baixar]');
        if (!btn) return;
        baixarModelo(btn.dataset.baixar, btn);
    });

    if (btnGerenciar) {
        btnGerenciar.addEventListener('click', async () => {
            await verificarStatus();
            if (!ultimoStatus) return;
            mostrarGate('Modelos disponiveis',
                'Baixe outros modelos ou troque o atual depois no header do chat.',
                { presets: true, presetsData: ultimoStatus.presets }
            );
        });
    }

    function esconderGate() {
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
                onEv(ev);
            }
        }
    }

    function prepararPullUI(textoInicial) {
        pullWrap.classList.remove('d-none');
        gateErro.classList.add('d-none');
        pullBar.style.width = '0%';
        pullPercent.textContent = '0%';
        pullStatus.textContent = textoInicial;
        pullDetalhe.textContent = '';
    }

    function exibirErro(msg) {
        gateErro.textContent = 'Erro: ' + msg;
        gateErro.classList.remove('d-none');
    }

    async function baixarModelo(slug, btn) {
        if (btn) btn.disabled = true;
        prepararPullUI(`Baixando ${slug}...`);
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
            setTimeout(verificarStatus, 600);
        } catch (err) {
            exibirErro(err.message);
            if (btn) btn.disabled = false;
        }
    }

    btnInstalar.addEventListener('click', async () => {
        btnInstalar.disabled = true;
        prepararPullUI('Preparando download do Ollama...');
        try {
            await consumirStream('/api/ai/instalar-ollama', {
                onEvent: (ev) => {
                    if (ev.erro) {
                        const det = ev.detalhe ? ` (${ev.detalhe})` : '';
                        throw new Error((ev.status || 'Falha na instalacao') + det);
                    }
                    if (ev.etapa === 'download') {
                        atualizarProgresso(ev);
                    } else if (ev.etapa === 'instalando') {
                        pullBar.style.width = '100%';
                        pullPercent.textContent = '';
                        pullStatus.textContent = ev.status || 'Instalando...';
                        pullDetalhe.textContent = 'Acompanhe o instalador do Ollama na sua tela.';
                    } else if (ev.etapa === 'concluido') {
                        pullStatus.textContent = ev.status || 'Instalado!';
                        pullDetalhe.textContent = '';
                    }
                },
            });
            setTimeout(verificarStatus, 800);
        } catch (err) {
            exibirErro(err.message);
            btnInstalar.disabled = false;
        }
    });

    btnIniciar.addEventListener('click', async () => {
        btnIniciar.disabled = true;
        gateErro.classList.add('d-none');
        try {
            const resp = await fetch('/api/ai/iniciar-ollama', { method: 'POST' });
            const data = await resp.json();
            if (!resp.ok || !data.ok) throw new Error(data.msg || ('HTTP ' + resp.status));
            pullWrap.classList.remove('d-none');
            pullStatus.textContent = 'Aguardando Ollama iniciar...';
            pullDetalhe.textContent = '';
            pullBar.style.width = '100%';
            pullPercent.textContent = '';

            for (let i = 0; i < 20; i++) {
                await new Promise(r => setTimeout(r, 1000));
                const ok = await verificarStatus();
                if (ok) return;
                const st = await (await fetch('/api/ai/status')).json();
                if (st.ollama_ativo) return;
            }
            throw new Error('Ollama nao respondeu a tempo. Tente novamente.');
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

    async function carregarChats() {
        try {
            const resp = await fetch('/api/ai/chats');
            const data = await resp.json();
            renderListaChats(data.chats || []);
        } catch (err) {
            listaChats.innerHTML = `<div class="text-danger small">Erro ao carregar</div>`;
        }
    }

    function renderListaChats(chats) {
        if (!chats.length) {
            listaChats.innerHTML = `<div class="text-secondary small text-center py-3">Sem conversas ainda.</div>`;
            return;
        }
        listaChats.innerHTML = chats.map((c) => `
            <div class="ai-chat__item ${chatAtual && chatAtual.id === c.id ? 'ai-chat__item--ativo' : ''}" data-id="${c.id}">
                <span class="ai-chat__item-titulo" title="${escapeHtml(c.titulo)}">${escapeHtml(c.titulo)}</span>
                <button class="ai-chat__item-acao" data-acao="excluir" data-id="${c.id}" title="Excluir">
                    <i class="bi bi-x-lg"></i>
                </button>
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
                resetarPainelMensagens();
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
        const resp = await fetch('/api/ai/chats', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ titulo: 'Nova conversa' }),
        });
        const data = await resp.json();
        await carregarChats();
        abrirChat(data.chat.id);
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
        resetarPainelMensagens();
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
            btnExcluir.classList.remove('d-none');
            input.disabled = false;
            btnEnviar.disabled = false;
            mensagensEl.innerHTML = '';
            (data.mensagens || []).forEach(m => adicionarMensagem(m.role, m.conteudo));
            if (!data.mensagens || !data.mensagens.length) {
                mensagensEl.innerHTML = `
                    <div class="ai-chat__empty text-secondary text-center py-5">
                        <i class="bi bi-chat-square-dots display-6 d-block mb-2"></i>
                        Envie sua primeira mensagem.
                    </div>`;
            }
            carregarChats();
            input.focus();
        } catch (err) {
            alert('Erro ao abrir conversa: ' + err.message);
        }
    }

    function resetarPainelMensagens() {
        tituloEl.textContent = 'Selecione uma conversa';
        btnRenomear.classList.add('d-none');
        btnExcluir.classList.add('d-none');
        input.disabled = true;
        btnEnviar.disabled = true;
        mensagensEl.innerHTML = `
            <div class="ai-chat__empty text-secondary text-center py-5">
                <i class="bi bi-chat-square-dots display-6 d-block mb-2"></i>
                Crie uma nova conversa para comecar.
            </div>`;
    }

    function adicionarMensagem(role, conteudo) {
        const vazio = mensagensEl.querySelector('.ai-chat__empty');
        if (vazio) vazio.remove();

        const wrap = document.createElement('div');
        wrap.className = `ai-chat__msg ai-chat__msg--${role}`;
        wrap.innerHTML = `
            <span class="ai-chat__msg-role">${role === 'user' ? 'Voce' : 'Assistente'}</span>
            <div class="ai-chat__msg-corpo"></div>
            <span class="ai-chat__msg-meta d-none"></span>
        `;
        const corpo = wrap.querySelector('.ai-chat__msg-corpo');
        renderMarkdown(corpo, conteudo);
        mensagensEl.appendChild(wrap);
        rolarFinal();
        return wrap;
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

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (enviando || !chatAtual) return;
        const texto = input.value.trim();
        if (!texto) return;

        enviando = true;
        input.disabled = true;
        btnEnviar.disabled = true;
        input.value = '';

        adicionarMensagem('user', texto);
        const wrapAssistente = adicionarMensagem('assistant', '');
        const corpoAssistente = wrapAssistente.querySelector('.ai-chat__msg-corpo');
        const cursor = document.createElement('span');
        cursor.className = 'ai-chat__cursor';
        corpoAssistente.appendChild(cursor);

        let acumulado = '';

        try {
            const resp = await fetch(`/api/ai/chats/${chatAtual.id}/mensagens`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ conteudo: texto, modelo: modeloAtual() }),
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

                    if (ev.tipo === 'delta') {
                        acumulado += ev.conteudo;
                        renderMarkdown(corpoAssistente, acumulado);
                        corpoAssistente.appendChild(cursor);
                        rolarFinal();
                    } else if (ev.tipo === 'erro') {
                        throw new Error(ev.msg || 'Erro do modelo');
                    } else if (ev.tipo === 'fim') {
                        cursor.remove();
                        renderMarkdown(corpoAssistente, acumulado);
                        exibirMetricas(wrapAssistente, ev.metricas);
                        rolarFinal();
                    }
                }
            }
        } catch (err) {
            cursor.remove();
            corpoAssistente.innerHTML = `<span class="text-danger">Erro: ${escapeHtml(err.message)}</span>`;
        } finally {
            enviando = false;
            input.disabled = false;
            btnEnviar.disabled = false;
            input.focus();
            carregarChats();
        }
    });

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            form.requestSubmit();
        }
    });

    verificarStatus();
})();
