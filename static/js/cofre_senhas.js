(function () {
    'use strict';

    // Senha-mestra e plaintext so em memoria — nunca localStorage/sessionStorage/cookie
    const state = {
        vaultId: null,
        nome: null,
        masterPassword: null,
        data: null,
        pendingId: null,
        pendingNome: null,
        idleTimer: null,
    };

    const IDLE_MS = 15 * 60 * 1000;
    const GUESSES_PER_SEC = 5000;

    const el = {
        lista: document.getElementById('cofre-view-lista'),
        aberto: document.getElementById('cofre-view-aberto'),
        grid: document.getElementById('cofre-grid'),
        vazio: document.getElementById('cofre-vazio'),
        titulo: document.getElementById('cofre-titulo'),
        entries: document.getElementById('cofre-entries'),
        entriesVazio: document.getElementById('cofre-entries-vazio'),
        busca: document.getElementById('cofre-busca'),
        novoForca: document.getElementById('cofre-novo-forca'),
        novoErro: document.getElementById('cofre-novo-erro'),
        unlockErro: document.getElementById('cofre-unlock-erro'),
        entradaErro: document.getElementById('cofre-entrada-erro'),
    };

    const modalNovo = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('cofre-modal-novo'));
    const modalUnlock = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('cofre-modal-unlock'));
    const modalEntrada = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('cofre-modal-entrada'));

    function wipePassword(str) {
        // Best-effort; JS strings sao imutaveis — so remove referencia
        return null;
    }

    function lock() {
        state.masterPassword = wipePassword(state.masterPassword);
        state.data = null;
        state.vaultId = null;
        state.nome = null;
        clearIdle();
        el.aberto.classList.add('d-none');
        el.lista.classList.remove('d-none');
        el.entries.innerHTML = '';
        el.busca.value = '';
    }

    function clearIdle() {
        if (state.idleTimer) {
            clearTimeout(state.idleTimer);
            state.idleTimer = null;
        }
    }

    function bumpIdle() {
        clearIdle();
        if (!state.masterPassword) return;
        state.idleTimer = setTimeout(() => {
            lock();
            carregarLista();
        }, IDLE_MS);
    }

    function uuid() {
        if (crypto.randomUUID) return crypto.randomUUID();
        return Array.from(crypto.getRandomValues(new Uint8Array(16)))
            .map((b) => b.toString(16).padStart(2, '0'))
            .join('');
    }

    function escapeHtml(s) {
        return String(s ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function formatBytes(n) {
        if (n < 1024) return n + ' B';
        if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
        return (n / (1024 * 1024)).toFixed(1) + ' MB';
    }

    function formatDate(iso) {
        if (!iso) return '';
        try {
            return new Date(iso).toLocaleString('pt-BR');
        } catch (_) {
            return iso;
        }
    }

    function charsetSize(pass) {
        let size = 0;
        if (/[0-9]/.test(pass)) size += 10;
        if (/[a-z]/.test(pass)) size += 26;
        if (/[A-Z]/.test(pass)) size += 26;
        if (/[^0-9a-zA-Z]/.test(pass)) size += 33;
        return size || 1;
    }

    function formatDuration(seconds) {
        if (!Number.isFinite(seconds) || seconds < 0) return 'incalculavel';
        if (seconds < 1) return 'menos de 1 segundo';
        const units = [
            { lim: 60, div: 1, s: 'segundo', p: 'segundos' },
            { lim: 3600, div: 60, s: 'minuto', p: 'minutos' },
            { lim: 86400, div: 3600, s: 'hora', p: 'horas' },
            { lim: 86400 * 365, div: 86400, s: 'dia', p: 'dias' },
            { lim: 86400 * 365 * 100, div: 86400 * 365, s: 'ano', p: 'anos' },
            { lim: 86400 * 365 * 1000, div: 86400 * 365 * 100, s: 'seculo', p: 'seculos' },
            { lim: Infinity, div: 86400 * 365 * 1e9, s: 'bilhao de anos', p: 'bilhoes de anos' },
        ];
        for (const u of units) {
            if (seconds < u.lim) {
                const n = Math.max(1, Math.round(seconds / u.div));
                return '~' + n.toLocaleString('pt-BR') + ' ' + (n === 1 ? u.s : u.p);
            }
        }
        return 'tempo astronomico';
    }

    function estimateCrack(pass) {
        if (!pass) return null;
        const log10Sec = pass.length * Math.log10(charsetSize(pass)) - Math.log10(2) - Math.log10(GUESSES_PER_SEC);
        const seconds = log10Sec > 308 ? Infinity : Math.pow(10, log10Sec);
        let nivel, cls;
        if (seconds < 86400 * 30) { nivel = 'Fraca'; cls = 'alert-danger'; }
        else if (seconds < 86400 * 365) { nivel = 'Moderada'; cls = 'alert-warning'; }
        else if (seconds < 86400 * 365 * 100) { nivel = 'Boa'; cls = 'alert-success'; }
        else { nivel = 'Forte'; cls = 'alert-success'; }
        return { nivel, cls, seconds, html: '<strong>' + nivel + '</strong> — brute force (~' + GUESSES_PER_SEC.toLocaleString('pt-BR') + ' tent./s): media ' + formatDuration(seconds) };
    }

    function renderForca(pass) {
        const box = el.novoForca;
        const est = estimateCrack(pass);
        if (!est) {
            box.className = 'alert py-2 px-3 small mb-0 mt-3 d-none';
            box.innerHTML = '';
            return est;
        }
        box.className = 'alert py-2 px-3 small mb-0 mt-3 ' + est.cls;
        box.innerHTML = est.html;
        return est;
    }

    function gerarSenha(len) {
        len = len || 20;
        const chars = 'abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$%&*-_=+';
        const bytes = crypto.getRandomValues(new Uint8Array(len));
        let out = '';
        for (let i = 0; i < len; i++) out += chars[bytes[i] % chars.length];
        return out;
    }

    async function api(url, opts) {
        const res = await fetch(url, opts);
        let body = null;
        const ct = res.headers.get('content-type') || '';
        if (ct.includes('application/json')) body = await res.json();
        if (!res.ok) {
            const msg = (body && (body.detail || body.msg)) || ('Erro ' + res.status);
            throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
        }
        return body;
    }

    async function carregarLista() {
        const itens = await api('/api/cofre');
        el.grid.innerHTML = '';
        if (!itens.length) {
            el.vazio.classList.remove('d-none');
            return;
        }
        el.vazio.classList.add('d-none');
        itens.forEach((v) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'cofre-card';
            btn.innerHTML =
                '<div class="cofre-card__icon"><i class="bi bi-safe2"></i></div>' +
                '<div class="cofre-card__nome">' + escapeHtml(v.nome) + '</div>' +
                '<div class="cofre-card__meta">' + formatBytes(v.bytes) + ' · ' + escapeHtml(formatDate(v.atualizado)) + '</div>';
            btn.addEventListener('click', () => pedirUnlock(v.id, v.nome));
            el.grid.appendChild(btn);
        });
    }

    function pedirUnlock(id, nome) {
        // Se ja desbloqueado o mesmo cofre nesta aba, reabre sem pedir senha
        if (state.vaultId === id && state.masterPassword && state.data) {
            mostrarAberto();
            return;
        }
        state.pendingId = id;
        state.pendingNome = nome;
        document.getElementById('cofre-unlock-nome').textContent = nome;
        document.getElementById('cofre-unlock-senha').value = '';
        el.unlockErro.classList.add('d-none');
        modalUnlock().show();
        setTimeout(() => document.getElementById('cofre-unlock-senha').focus(), 300);
    }

    async function desbloquear() {
        const senha = document.getElementById('cofre-unlock-senha').value;
        el.unlockErro.classList.add('d-none');
        if (!senha) {
            el.unlockErro.textContent = 'Informe a senha-mestra';
            el.unlockErro.classList.remove('d-none');
            return;
        }
        try {
            const remote = await api('/api/cofre/' + state.pendingId);
            const plain = await HubGcm.decrypt(remote.blob, senha);
            const data = JSON.parse(plain);
            if (!data || data.v !== 1 || !Array.isArray(data.entries)) {
                throw new Error('Conteudo do cofre invalido');
            }
            // limpa campo do modal antes de fechar
            document.getElementById('cofre-unlock-senha').value = '';
            state.vaultId = remote.id;
            state.nome = remote.nome;
            state.masterPassword = senha;
            state.data = data;
            state.pendingId = null;
            modalUnlock().hide();
            mostrarAberto();
            bumpIdle();
        } catch (e) {
            document.getElementById('cofre-unlock-senha').value = '';
            el.unlockErro.textContent = 'Senha incorreta ou arquivo adulterado';
            el.unlockErro.classList.remove('d-none');
        }
    }

    function mostrarAberto() {
        el.lista.classList.add('d-none');
        el.aberto.classList.remove('d-none');
        el.titulo.textContent = state.nome;
        renderEntries();
    }

    function renderEntries() {
        const q = (el.busca.value || '').trim().toLowerCase();
        const entries = (state.data.entries || []).filter((e) => {
            if (!q) return true;
            return [e.titulo, e.usuario, e.url, e.notas].join(' ').toLowerCase().includes(q);
        }).slice().sort((a, b) => (a.titulo || '').localeCompare(b.titulo || '', 'pt'));

        el.entries.innerHTML = '';
        if (!entries.length) {
            el.entriesVazio.classList.remove('d-none');
            return;
        }
        el.entriesVazio.classList.add('d-none');
        entries.forEach((e) => {
            const row = document.createElement('div');
            row.className = 'cofre-entry';
            const userLine = e.usuario ? escapeHtml(e.usuario) : '<span class="text-secondary">sem usuario</span>';
            const urlLine = e.url
                ? ' · <a href="' + escapeHtml(e.url) + '" target="_blank" rel="noopener">' + escapeHtml(e.url) + '</a>'
                : '';
            row.innerHTML =
                '<div>' +
                '<div class="cofre-entry__titulo">' + escapeHtml(e.titulo || 'Sem titulo') + '</div>' +
                '<div class="cofre-entry__meta">' + userLine + urlLine + '</div>' +
                '</div>' +
                '<div class="cofre-entry__acoes">' +
                '<button type="button" class="btn btn-sm btn-outline-secondary" data-act="copy-user" title="Copiar usuario"><i class="bi bi-person"></i></button>' +
                '<button type="button" class="btn btn-sm btn-outline-primary" data-act="copy-pass" title="Copiar senha"><i class="bi bi-key"></i></button>' +
                '<button type="button" class="btn btn-sm btn-outline-secondary" data-act="edit" title="Editar"><i class="bi bi-pencil"></i></button>' +
                '</div>';
            row.querySelector('[data-act="copy-user"]').addEventListener('click', () => copiar(e.usuario || '', row.querySelector('[data-act="copy-user"]')));
            row.querySelector('[data-act="copy-pass"]').addEventListener('click', () => copiar(e.senha || '', row.querySelector('[data-act="copy-pass"]')));
            row.querySelector('[data-act="edit"]').addEventListener('click', () => abrirEntrada(e));
            el.entries.appendChild(row);
        });
    }

    async function copiar(texto, btn) {
        bumpIdle();
        try {
            await navigator.clipboard.writeText(texto);
            const prev = btn.innerHTML;
            btn.innerHTML = '<i class="bi bi-check2"></i>';
            setTimeout(() => { btn.innerHTML = prev; }, 1200);
        } catch (_) {}
    }

    async function persistir() {
        if (!state.vaultId || !state.masterPassword || !state.data) {
            throw new Error('Cofre nao desbloqueado');
        }
        const blob = await HubGcm.encrypt(JSON.stringify(state.data), state.masterPassword);
        await api('/api/cofre/' + state.vaultId, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ blob }),
        });
        bumpIdle();
    }

    async function criarCofre() {
        const nome = document.getElementById('cofre-novo-nome').value.trim();
        const senha = document.getElementById('cofre-novo-senha').value;
        const senha2 = document.getElementById('cofre-novo-senha2').value;
        el.novoErro.classList.add('d-none');
        try {
            if (!nome) throw new Error('Informe um nome');
            if (!senha) throw new Error('Informe a senha-mestra');
            if (senha !== senha2) throw new Error('As senhas nao coincidem');
            const est = estimateCrack(senha);
            if (est && est.seconds < 86400 * 30) {
                throw new Error('Senha-mestra fraca demais. Use mais caracteres e variedade.');
            }
            const data = { v: 1, entries: [] };
            const blob = await HubGcm.encrypt(JSON.stringify(data), senha);
            const created = await api('/api/cofre', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ nome, blob }),
            });
            document.getElementById('cofre-novo-senha').value = '';
            document.getElementById('cofre-novo-senha2').value = '';
            document.getElementById('cofre-novo-nome').value = '';
            modalNovo().hide();
            state.vaultId = created.id;
            state.nome = created.nome;
            state.masterPassword = senha;
            state.data = data;
            await carregarLista();
            mostrarAberto();
            bumpIdle();
        } catch (e) {
            el.novoErro.textContent = e.message || 'Erro ao criar';
            el.novoErro.classList.remove('d-none');
        }
    }

    function abrirEntrada(entry) {
        bumpIdle();
        const isNew = !entry;
        document.getElementById('cofre-entrada-titulo-modal').textContent = isNew ? 'Nova entrada' : 'Editar entrada';
        document.getElementById('cofre-entrada-id').value = entry ? entry.id : '';
        document.getElementById('cofre-entrada-titulo').value = entry ? (entry.titulo || '') : '';
        document.getElementById('cofre-entrada-url').value = entry ? (entry.url || '') : '';
        document.getElementById('cofre-entrada-usuario').value = entry ? (entry.usuario || '') : '';
        document.getElementById('cofre-entrada-senha').value = entry ? (entry.senha || '') : '';
        document.getElementById('cofre-entrada-notas').value = entry ? (entry.notas || '') : '';
        el.entradaErro.classList.add('d-none');
        const btnEx = document.getElementById('cofre-entrada-excluir');
        btnEx.classList.toggle('d-none', isNew);
        modalEntrada().show();
    }

    async function salvarEntrada() {
        bumpIdle();
        el.entradaErro.classList.add('d-none');
        try {
            const id = document.getElementById('cofre-entrada-id').value;
            const titulo = document.getElementById('cofre-entrada-titulo').value.trim();
            if (!titulo) throw new Error('Informe um titulo');
            const agora = new Date().toISOString();
            const payload = {
                id: id || uuid(),
                titulo,
                url: document.getElementById('cofre-entrada-url').value.trim(),
                usuario: document.getElementById('cofre-entrada-usuario').value,
                senha: document.getElementById('cofre-entrada-senha').value,
                notas: document.getElementById('cofre-entrada-notas').value,
                atualizado: agora,
            };
            if (!id) payload.criado = agora;
            const idx = state.data.entries.findIndex((e) => e.id === payload.id);
            if (idx >= 0) {
                payload.criado = state.data.entries[idx].criado || agora;
                state.data.entries[idx] = payload;
            } else {
                state.data.entries.push(payload);
            }
            await persistir();
            // limpa campos do modal (senha da entrada)
            document.getElementById('cofre-entrada-senha').value = '';
            modalEntrada().hide();
            renderEntries();
        } catch (e) {
            el.entradaErro.textContent = e.message || 'Erro ao salvar';
            el.entradaErro.classList.remove('d-none');
        }
    }

    async function excluirEntrada() {
        const id = document.getElementById('cofre-entrada-id').value;
        if (!id || !confirm('Excluir esta entrada?')) return;
        state.data.entries = state.data.entries.filter((e) => e.id !== id);
        await persistir();
        document.getElementById('cofre-entrada-senha').value = '';
        modalEntrada().hide();
        renderEntries();
    }

    async function excluirCofre() {
        if (!state.vaultId) return;
        if (!confirm('Excluir este cofre permanentemente?')) return;
        const id = state.vaultId;
        lock();
        await api('/api/cofre/' + id, { method: 'DELETE' });
        await carregarLista();
    }

    async function importarArquivo(file) {
        const fd = new FormData();
        fd.append('arquivo', file);
        await api('/api/cofre/importar', { method: 'POST', body: fd });
        await carregarLista();
    }

    // toggles
    document.querySelectorAll('.js-cofre-toggle').forEach((btn) => {
        btn.addEventListener('click', () => {
            const inp = document.getElementById(btn.dataset.target);
            if (!inp) return;
            const show = inp.type === 'password';
            inp.type = show ? 'text' : 'password';
            btn.innerHTML = show ? '<i class="bi bi-eye-slash"></i>' : '<i class="bi bi-eye"></i>';
        });
    });

    document.getElementById('cofre-btn-novo')?.addEventListener('click', () => {
        document.getElementById('cofre-novo-nome').value = '';
        document.getElementById('cofre-novo-senha').value = '';
        document.getElementById('cofre-novo-senha2').value = '';
        el.novoErro.classList.add('d-none');
        renderForca('');
        modalNovo().show();
    });
    document.getElementById('cofre-novo-senha')?.addEventListener('input', (e) => renderForca(e.target.value));
    document.getElementById('cofre-novo-salvar')?.addEventListener('click', criarCofre);
    document.getElementById('cofre-unlock-ok')?.addEventListener('click', desbloquear);
    document.getElementById('cofre-unlock-senha')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') desbloquear();
    });
    document.getElementById('cofre-btn-voltar')?.addEventListener('click', () => {
        lock();
        carregarLista();
    });
    document.getElementById('cofre-btn-add')?.addEventListener('click', () => abrirEntrada(null));
    document.getElementById('cofre-entrada-salvar')?.addEventListener('click', salvarEntrada);
    document.getElementById('cofre-entrada-excluir')?.addEventListener('click', excluirEntrada);
    document.getElementById('cofre-entrada-gerar')?.addEventListener('click', () => {
        document.getElementById('cofre-entrada-senha').value = gerarSenha(20);
        document.getElementById('cofre-entrada-senha').type = 'text';
    });
    document.getElementById('cofre-btn-excluir-cofre')?.addEventListener('click', excluirCofre);
    document.getElementById('cofre-btn-export')?.addEventListener('click', () => {
        if (state.vaultId) window.location.href = '/api/cofre/' + state.vaultId + '/exportar';
    });
    document.getElementById('cofre-import-file')?.addEventListener('change', async (e) => {
        const file = e.target.files && e.target.files[0];
        e.target.value = '';
        if (!file) return;
        try {
            await importarArquivo(file);
        } catch (err) {
            alert(err.message || 'Falha ao importar');
        }
    });
    el.busca?.addEventListener('input', () => {
        bumpIdle();
        renderEntries();
    });

    ['click', 'keydown', 'mousemove'].forEach((evt) => {
        document.addEventListener(evt, () => {
            if (state.masterPassword) bumpIdle();
        }, { passive: true });
    });

    window.addEventListener('pagehide', () => {
        state.masterPassword = null;
        state.data = null;
    });
    window.addEventListener('beforeunload', () => {
        state.masterPassword = null;
        state.data = null;
    });

    // limpar escopo — apos limpeza, volta pra lista
    document.querySelectorAll('.btn-limpar-escopo[data-escopo="cofre-senhas"]').forEach((btn) => {
        btn.addEventListener('click', () => {
            // app.js cuida do POST; so resetamos UI depois
            setTimeout(() => { lock(); carregarLista(); }, 800);
        });
    });

    carregarLista().catch((e) => {
        el.vazio.textContent = e.message || 'Erro ao listar cofres';
        el.vazio.classList.remove('d-none');
    });
})();
