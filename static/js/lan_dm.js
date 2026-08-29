(function () {
    const LS_APELIDO = 'lan_dm_apelido';
    const CANAL_GERAL = '__geral__';

    const gate = document.getElementById('lan-gate');
    const gateErro = document.getElementById('lan-gate-erro');
    const formApelido = document.getElementById('lan-form-apelido');
    const inputApelido = document.getElementById('lan-apelido-input');

    const chat = document.getElementById('lan-chat');
    const meuApelidoEl = document.getElementById('lan-meu-apelido');
    const statusEl = document.getElementById('lan-status');
    const onlineEl = document.getElementById('lan-online');
    const mensagensEl = document.getElementById('lan-mensagens');
    const canalTitulo = document.getElementById('lan-canal-titulo');
    const canalSub = document.getElementById('lan-canal-sub');
    const formEnviar = document.getElementById('lan-form-enviar');
    const textoEl = document.getElementById('lan-texto');
    const btnAnexo = document.getElementById('lan-btn-anexo');
    const fileInput = document.getElementById('lan-arquivo');
    const anexosEl = document.getElementById('lan-anexos');
    const btnEnviar = document.getElementById('lan-btn-enviar');

    let apelido = '';
    let canalAtual = CANAL_GERAL;
    let ultimoId = 0;
    /** @type {WebSocket|null} */
    let ws = null;
    /** @type {File[]} */
    let anexos = [];
    let enviando = false;

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

    function setStatus(estado, texto) {
        const map = {
            ok: 'text-bg-success',
            warn: 'text-bg-warning',
            erro: 'text-bg-danger',
            off: 'text-bg-secondary',
        };
        statusEl.className = 'badge ' + (map[estado] || 'text-bg-secondary');
        statusEl.innerHTML = '<i class="bi bi-circle-fill me-1"></i> ' + escapeHtml(texto);
    }

    function mostrarErroGate(msg) {
        gateErro.textContent = msg;
        gateErro.classList.remove('d-none');
    }

    function esconderErroGate() {
        gateErro.classList.add('d-none');
    }

    function wsUrl() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        return proto + '//' + location.host + '/ws/lan-dm';
    }

    function renderAnexos() {
        if (!anexos.length) {
            anexosEl.classList.add('d-none');
            anexosEl.innerHTML = '';
            return;
        }
        anexosEl.classList.remove('d-none');
        anexosEl.innerHTML = anexos.map((f, i) => (
            '<span class="lan-chat__anexo-chip">' +
            '<i class="bi bi-file-earmark"></i> ' + escapeHtml(f.name) +
            ' <button type="button" class="btn btn-sm btn-link p-0 text-danger" data-rm="' + i + '" aria-label="Remover">&times;</button>' +
            '</span>'
        )).join('');
        anexosEl.querySelectorAll('[data-rm]').forEach((btn) => {
            btn.addEventListener('click', () => {
                anexos.splice(Number(btn.getAttribute('data-rm')), 1);
                renderAnexos();
            });
        });
    }

    function scrollFim() {
        requestAnimationFrame(() => {
            mensagensEl.scrollTop = mensagensEl.scrollHeight;
        });
    }

    function renderMsg(msg) {
        const eu = msg.remetente === apelido;
        const div = document.createElement('div');
        div.className = 'lan-msg' + (eu ? ' lan-msg--eu' : '');
        div.dataset.id = String(msg.id);

        let corpo = '';
        if (msg.conteudo) {
            corpo += '<p class="lan-msg__texto">' + escapeHtml(msg.conteudo) + '</p>';
        }
        if (msg.tem_arquivo && msg.arquivo_nome) {
            corpo += '<div class="lan-msg__arquivo mt-1">' +
                '<a href="/api/lan-dm/arquivos/' + msg.id + '" download>' +
                '<i class="bi bi-download"></i> ' + escapeHtml(msg.arquivo_nome) +
                ' <span class="text-secondary">(' + formatBytes(msg.arquivo_bytes) + ')</span>' +
                '</a></div>';
        }

        const dest = msg.destinatario && msg.destinatario !== CANAL_GERAL
            ? ' → ' + escapeHtml(msg.destinatario)
            : '';

        div.innerHTML =
            '<div class="lan-msg__meta">' + escapeHtml(msg.remetente) + dest +
            ' · ' + escapeHtml(msg.criado_em || '') + '</div>' + corpo;

        return div;
    }

    function appendMensagem(msg) {
        if (!msg || !msg.id) return;
        if (mensagensEl.querySelector('[data-id="' + msg.id + '"]')) return;

        const dest = msg.destinatario || CANAL_GERAL;
        const relevante = canalAtual === CANAL_GERAL
            ? dest === CANAL_GERAL
            : (
                (msg.remetente === apelido && dest === canalAtual) ||
                (msg.remetente === canalAtual && dest === apelido)
            );
        if (!relevante) return;

        mensagensEl.appendChild(renderMsg(msg));
        ultimoId = Math.max(ultimoId, msg.id);
        scrollFim();
    }

    async function carregarHistorico() {
        const params = new URLSearchParams({
            apelido: apelido,
            destinatario: canalAtual === CANAL_GERAL ? '' : canalAtual,
            desde_id: '0',
        });
        const resp = await fetch('/api/lan-dm/mensagens?' + params.toString());
        if (!resp.ok) return;
        const data = await resp.json();
        mensagensEl.innerHTML = '';
        ultimoId = 0;
        (data.mensagens || []).forEach((m) => appendMensagem(m));
    }

    function marcarCanalAtivo() {
        document.querySelectorAll('.lan-chat__canal, .lan-chat__peer').forEach((el) => {
            const alvo = el.getAttribute('data-canal') || el.getAttribute('data-peer');
            el.classList.toggle('lan-chat__canal--ativo', alvo === canalAtual);
            el.classList.toggle('lan-chat__peer--ativo', alvo === canalAtual);
        });
        if (canalAtual === CANAL_GERAL) {
            canalTitulo.textContent = 'Geral';
            canalSub.textContent = 'Mensagens visiveis para todos na LAN';
        } else {
            canalTitulo.textContent = canalAtual;
            canalSub.textContent = 'Conversa direta com ' + canalAtual;
        }
    }

    function selecionarCanal(dest) {
        canalAtual = dest || CANAL_GERAL;
        marcarCanalAtivo();
        carregarHistorico();
    }

    function renderOnline(lista) {
        const outros = (lista || []).filter((n) => n !== apelido);
        if (!outros.length) {
            onlineEl.innerHTML = '<div class="text-secondary small py-2">Ninguem mais online.</div>';
            return;
        }
        onlineEl.innerHTML = outros.map((nome) => (
            '<button type="button" class="lan-chat__peer' +
            (canalAtual === nome ? ' lan-chat__peer--ativo' : '') +
            '" data-peer="' + escapeHtml(nome) + '">' +
            '<i class="bi bi-pc-display me-2"></i>' + escapeHtml(nome) +
            '</button>'
        )).join('');
        onlineEl.querySelectorAll('.lan-chat__peer').forEach((btn) => {
            btn.addEventListener('click', () => selecionarCanal(btn.getAttribute('data-peer')));
        });
    }

    function conectarWs() {
        if (ws) {
            try { ws.close(); } catch (_) {}
            ws = null;
        }
        setStatus('warn', 'conectando...');
        ws = new WebSocket(wsUrl());

        ws.addEventListener('open', () => {
            ws.send(JSON.stringify({ tipo: 'join', apelido: apelido }));
        });

        ws.addEventListener('message', (ev) => {
            let data;
            try { data = JSON.parse(ev.data); } catch (_) { return; }
            if (data.tipo === 'joined') {
                setStatus('ok', 'online');
                renderOnline(data.online || []);
                return;
            }
            if (data.tipo === 'presence') {
                renderOnline(data.online || []);
                return;
            }
            if (data.tipo === 'mensagem' && data.msg) {
                appendMensagem(data.msg);
            }
        });

        ws.addEventListener('close', (ev) => {
            setStatus('erro', 'desconectado');
            if (ev.code === 4409) {
                mostrarErroGate('Apelido ja em uso por outro PC. Escolha outro.');
                gate.classList.remove('d-none');
                chat.classList.add('d-none');
                localStorage.removeItem(LS_APELIDO);
                return;
            }
            if (ev.code === 4401) {
                location.href = '/login?next=' + encodeURIComponent(location.pathname);
                return;
            }
            setTimeout(() => {
                if (apelido && !chat.classList.contains('d-none')) conectarWs();
            }, 2500);
        });

        ws.addEventListener('error', () => setStatus('erro', 'erro de conexao'));
    }

    async function entrar(nome) {
        apelido = nome.trim();
        if (!apelido) return;
        esconderErroGate();
        localStorage.setItem(LS_APELIDO, apelido);
        meuApelidoEl.textContent = apelido;
        gate.classList.add('d-none');
        chat.classList.remove('d-none');
        canalAtual = CANAL_GERAL;
        marcarCanalAtivo();
        await carregarHistorico();
        conectarWs();
    }

    async function enviarMensagem(ev) {
        ev.preventDefault();
        if (enviando) return;
        const texto = (textoEl.value || '').trim();
        if (!texto && !anexos.length) return;

        enviando = true;
        btnEnviar.disabled = true;

        const destParam = canalAtual === CANAL_GERAL ? '' : canalAtual;
        const arquivos = anexos.slice();
        const lotes = arquivos.length ? arquivos : [null];

        try {
            for (let i = 0; i < lotes.length; i++) {
                const fd = new FormData();
                fd.append('apelido', apelido);
                fd.append('destinatario', destParam);
                fd.append('conteudo', i === 0 ? texto : '');
                if (lotes[i]) fd.append('arquivo', lotes[i], lotes[i].name);

                const resp = await fetch('/api/lan-dm/mensagens', { method: 'POST', body: fd });
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok) {
                    throw new Error(data.detail || 'Falha ao enviar');
                }
                if (data.mensagem) appendMensagem(data.mensagem);
            }
            textoEl.value = '';
            anexos = [];
            renderAnexos();
        } catch (err) {
            alert(err.message || 'Erro ao enviar');
        } finally {
            enviando = false;
            btnEnviar.disabled = false;
        }
    }

    document.querySelector('.lan-chat__canal[data-canal="' + CANAL_GERAL + '"]')
        ?.addEventListener('click', () => selecionarCanal(CANAL_GERAL));

    formApelido?.addEventListener('submit', (ev) => {
        ev.preventDefault();
        entrar(inputApelido.value);
    });

    formEnviar?.addEventListener('submit', enviarMensagem);

    btnAnexo?.addEventListener('click', () => fileInput?.click());
    fileInput?.addEventListener('change', () => {
        const files = Array.from(fileInput.files || []);
        fileInput.value = '';
        if (!files.length) return;
        anexos = anexos.concat(files).slice(0, 5);
        renderAnexos();
    });

    textoEl?.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' && !ev.shiftKey) {
            ev.preventDefault();
            formEnviar.requestSubmit();
        }
    });

    const salvo = localStorage.getItem(LS_APELIDO);
    if (salvo) {
        inputApelido.value = salvo;
        entrar(salvo);
    }
})();
