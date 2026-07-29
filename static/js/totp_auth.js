(function () {
    'use strict';

    const API = '/api/totp';
    const IDLE_MS = 15 * 60 * 1000;
    const GUESSES_PER_SEC = 5000;
    const BASE32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';

    const state = {
        vaultId: null,
        nome: null,
        masterPassword: null,
        data: null,
        pendingId: null,
        pendingNome: null,
        idleTimer: null,
        tickTimer: null,
        codes: {},
    };

    const el = {
        lista: document.getElementById('totp-view-lista'),
        aberto: document.getElementById('totp-view-aberto'),
        grid: document.getElementById('totp-grid'),
        vazio: document.getElementById('totp-vazio'),
        titulo: document.getElementById('totp-titulo'),
        accounts: document.getElementById('totp-accounts'),
        accountsVazio: document.getElementById('totp-accounts-vazio'),
        busca: document.getElementById('totp-busca'),
        novoForca: document.getElementById('totp-novo-forca'),
        novoErro: document.getElementById('totp-novo-erro'),
        unlockErro: document.getElementById('totp-unlock-erro'),
        contaErro: document.getElementById('totp-conta-erro'),
    };

    const modalNovo = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('totp-modal-novo'));
    const modalUnlock = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('totp-modal-unlock'));
    const modalConta = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('totp-modal-conta'));

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
        try { return new Date(iso).toLocaleString('pt-BR'); } catch (_) { return iso; }
    }

    function base32Decode(input) {
        const cleaned = String(input || '').toUpperCase().replace(/[^A-Z2-7]/g, '');
        if (!cleaned) throw new Error('Segredo Base32 vazio');
        let bits = '';
        for (const c of cleaned) {
            const val = BASE32.indexOf(c);
            if (val < 0) throw new Error('Segredo Base32 invalido');
            bits += val.toString(2).padStart(5, '0');
        }
        const bytes = [];
        for (let i = 0; i + 8 <= bits.length; i += 8) {
            bytes.push(parseInt(bits.slice(i, i + 8), 2));
        }
        return new Uint8Array(bytes);
    }

    function counterToBytes(counter) {
        const buf = new ArrayBuffer(8);
        const view = new DataView(buf);
        // high 32 then low 32
        const high = Math.floor(counter / 0x100000000);
        const low = counter >>> 0;
        view.setUint32(0, high);
        view.setUint32(4, low);
        return new Uint8Array(buf);
    }

    async function hotp(secretBytes, counter, digits) {
        const key = await crypto.subtle.importKey(
            'raw',
            secretBytes,
            { name: 'HMAC', hash: 'SHA-1' },
            false,
            ['sign']
        );
        const mac = new Uint8Array(await crypto.subtle.sign('HMAC', key, counterToBytes(counter)));
        const offset = mac[mac.length - 1] & 0x0f;
        const bin =
            ((mac[offset] & 0x7f) << 24) |
            ((mac[offset + 1] & 0xff) << 16) |
            ((mac[offset + 2] & 0xff) << 8) |
            (mac[offset + 3] & 0xff);
        const mod = 10 ** digits;
        return String(bin % mod).padStart(digits, '0');
    }

    async function totp(secret, digits, period, nowMs) {
        const secretBytes = base32Decode(secret);
        const counter = Math.floor((nowMs / 1000) / period);
        const code = await hotp(secretBytes, counter, digits);
        const remaining = period - Math.floor((nowMs / 1000) % period);
        return { code, remaining, period };
    }

    function parseOtpauth(uri) {
        const raw = String(uri || '').trim();
        if (!raw.toLowerCase().startsWith('otpauth://')) return null;
        let url;
        try { url = new URL(raw); } catch (_) { return null; }
        if (url.hostname.toLowerCase() !== 'totp') return null;
        const params = url.searchParams;
        const secret = params.get('secret') || '';
        const issuerParam = params.get('issuer') || '';
        let label = decodeURIComponent(url.pathname.replace(/^\//, ''));
        let issuer = issuerParam;
        if (label.includes(':')) {
            const parts = label.split(':');
            if (!issuer) issuer = parts[0];
            label = parts.slice(1).join(':').trim();
        }
        const digits = Number(params.get('digits') || 6);
        const period = Number(params.get('period') || 30);
        return {
            issuer: issuer.trim(),
            label: label.trim(),
            secret: secret.replace(/\s+/g, '').toUpperCase(),
            digits: digits === 8 ? 8 : 6,
            period: period >= 15 && period <= 120 ? period : 30,
        };
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
            { lim: Infinity, div: 86400 * 365 * 100, s: 'seculo', p: 'seculos' },
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

    function stopTick() {
        if (state.tickTimer) {
            clearInterval(state.tickTimer);
            state.tickTimer = null;
        }
    }

    function lock() {
        stopTick();
        state.masterPassword = null;
        state.data = null;
        state.codes = {};
        state.vaultId = null;
        state.nome = null;
        clearIdle();
        el.aberto.classList.add('d-none');
        el.lista.classList.remove('d-none');
        el.accounts.innerHTML = '';
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
        const itens = await api(API);
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
                '<div class="cofre-card__icon"><i class="bi bi-phone"></i></div>' +
                '<div class="cofre-card__nome">' + escapeHtml(v.nome) + '</div>' +
                '<div class="cofre-card__meta">' + formatBytes(v.bytes) + ' · ' + escapeHtml(formatDate(v.atualizado)) + '</div>';
            btn.addEventListener('click', () => pedirUnlock(v.id, v.nome));
            el.grid.appendChild(btn);
        });
    }

    function pedirUnlock(id, nome) {
        if (state.vaultId === id && state.masterPassword && state.data) {
            mostrarAberto();
            return;
        }
        state.pendingId = id;
        state.pendingNome = nome;
        document.getElementById('totp-unlock-nome').textContent = nome;
        document.getElementById('totp-unlock-senha').value = '';
        el.unlockErro.classList.add('d-none');
        modalUnlock().show();
        setTimeout(() => document.getElementById('totp-unlock-senha').focus(), 300);
    }

    async function desbloquear() {
        const senha = document.getElementById('totp-unlock-senha').value;
        el.unlockErro.classList.add('d-none');
        if (!senha) {
            el.unlockErro.textContent = 'Informe a senha-mestra';
            el.unlockErro.classList.remove('d-none');
            return;
        }
        try {
            const remote = await api(API + '/' + state.pendingId);
            const plain = await HubGcm.decrypt(remote.blob, senha);
            const data = JSON.parse(plain);
            if (!data || data.v !== 1 || !Array.isArray(data.accounts)) {
                throw new Error('Conteudo invalido');
            }
            document.getElementById('totp-unlock-senha').value = '';
            state.vaultId = remote.id;
            state.nome = remote.nome;
            state.masterPassword = senha;
            state.data = data;
            state.pendingId = null;
            modalUnlock().hide();
            mostrarAberto();
            bumpIdle();
        } catch (_) {
            document.getElementById('totp-unlock-senha').value = '';
            el.unlockErro.textContent = 'Senha incorreta ou arquivo adulterado';
            el.unlockErro.classList.remove('d-none');
        }
    }

    function mostrarAberto() {
        el.lista.classList.add('d-none');
        el.aberto.classList.remove('d-none');
        el.titulo.textContent = state.nome;
        renderAccounts();
        startTick();
    }

    function filteredAccounts() {
        const q = (el.busca.value || '').trim().toLowerCase();
        return (state.data.accounts || []).filter((a) => {
            if (!q) return true;
            return [a.issuer, a.label].join(' ').toLowerCase().includes(q);
        }).slice().sort((a, b) => {
            const ka = (a.issuer || '') + ' ' + (a.label || '');
            const kb = (b.issuer || '') + ' ' + (b.label || '');
            return ka.localeCompare(kb, 'pt');
        });
    }

    function formatCode(code) {
        if (!code) return '------';
        if (code.length === 6) return code.slice(0, 3) + ' ' + code.slice(3);
        if (code.length === 8) return code.slice(0, 4) + ' ' + code.slice(4);
        return code;
    }

    function renderAccounts() {
        const list = filteredAccounts();
        el.accounts.innerHTML = '';
        if (!list.length) {
            el.accountsVazio.classList.remove('d-none');
            return;
        }
        el.accountsVazio.classList.add('d-none');
        list.forEach((a) => {
            const info = state.codes[a.id] || {};
            const remaining = info.remaining || 0;
            const period = a.period || 30;
            const pct = Math.max(0, Math.min(100, (remaining / period) * 100));
            const urgent = remaining <= 5;
            const row = document.createElement('div');
            row.className = 'totp-card';
            row.dataset.id = a.id;
            row.innerHTML =
                '<div>' +
                '<div class="totp-card__issuer">' + escapeHtml(a.issuer || 'Conta') + '</div>' +
                '<div class="totp-card__label">' + escapeHtml(a.label || '') + '</div>' +
                '</div>' +
                '<div class="totp-card__right">' +
                '<div class="totp-card__code" data-act="copy" title="Copiar">' + escapeHtml(formatCode(info.code)) + '</div>' +
                '<div class="totp-card__timer"><div class="totp-card__timer-bar' + (urgent ? ' is-urgent' : '') + '" style="width:' + pct + '%"></div></div>' +
                '</div>' +
                '<div class="totp-card__acoes">' +
                '<button type="button" class="btn btn-sm btn-outline-primary" data-act="copy"><i class="bi bi-clipboard"></i> Copiar</button>' +
                '<button type="button" class="btn btn-sm btn-outline-secondary" data-act="edit"><i class="bi bi-pencil"></i></button>' +
                '</div>';
            row.querySelectorAll('[data-act="copy"]').forEach((btn) => {
                btn.addEventListener('click', () => copiar(info.code || '', btn));
            });
            row.querySelector('[data-act="edit"]').addEventListener('click', () => abrirConta(a));
            el.accounts.appendChild(row);
        });
    }

    function updateTimersDom() {
        el.accounts.querySelectorAll('.totp-card').forEach((row) => {
            const id = row.dataset.id;
            const info = state.codes[id];
            if (!info) return;
            const codeEl = row.querySelector('.totp-card__code');
            const bar = row.querySelector('.totp-card__timer-bar');
            const account = (state.data.accounts || []).find((a) => a.id === id);
            const period = (account && account.period) || 30;
            if (codeEl) codeEl.textContent = formatCode(info.code);
            if (bar) {
                const pct = Math.max(0, Math.min(100, (info.remaining / period) * 100));
                bar.style.width = pct + '%';
                bar.classList.toggle('is-urgent', info.remaining <= 5);
            }
        });
    }

    async function refreshCodes() {
        if (!state.data || !state.data.accounts) return;
        const now = Date.now();
        const next = {};
        await Promise.all((state.data.accounts || []).map(async (a) => {
            try {
                next[a.id] = await totp(a.secret, a.digits || 6, a.period || 30, now);
            } catch (_) {
                next[a.id] = { code: '??????', remaining: 0, period: a.period || 30 };
            }
        }));
        state.codes = next;
        updateTimersDom();
    }

    function startTick() {
        stopTick();
        refreshCodes().then(() => renderAccounts());
        state.tickTimer = setInterval(() => {
            refreshCodes();
        }, 1000);
    }

    async function copiar(texto, btn) {
        bumpIdle();
        try {
            await navigator.clipboard.writeText(String(texto || '').replace(/\s+/g, ''));
            const prev = btn.innerHTML;
            btn.innerHTML = '<i class="bi bi-check2"></i>';
            setTimeout(() => { btn.innerHTML = prev; }, 1200);
        } catch (_) {}
    }

    async function persistir() {
        if (!state.vaultId || !state.masterPassword || !state.data) {
            throw new Error('Vault nao desbloqueado');
        }
        const blob = await HubGcm.encrypt(JSON.stringify(state.data), state.masterPassword);
        await api(API + '/' + state.vaultId, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ blob }),
        });
        bumpIdle();
    }

    async function criarVault() {
        const nome = document.getElementById('totp-novo-nome').value.trim();
        const senha = document.getElementById('totp-novo-senha').value;
        const senha2 = document.getElementById('totp-novo-senha2').value;
        el.novoErro.classList.add('d-none');
        try {
            if (!nome) throw new Error('Informe um nome');
            if (!senha) throw new Error('Informe a senha-mestra');
            if (senha !== senha2) throw new Error('As senhas nao coincidem');
            const est = estimateCrack(senha);
            if (est && est.seconds < 86400 * 30) {
                throw new Error('Senha-mestra fraca demais. Use mais caracteres e variedade.');
            }
            const data = { v: 1, accounts: [] };
            const blob = await HubGcm.encrypt(JSON.stringify(data), senha);
            const created = await api(API, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ nome, blob }),
            });
            document.getElementById('totp-novo-senha').value = '';
            document.getElementById('totp-novo-senha2').value = '';
            document.getElementById('totp-novo-nome').value = '';
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

    function abrirConta(account) {
        bumpIdle();
        const isNew = !account;
        document.getElementById('totp-conta-titulo-modal').textContent = isNew ? 'Nova conta' : 'Editar conta';
        document.getElementById('totp-conta-id').value = account ? account.id : '';
        document.getElementById('totp-conta-uri').value = '';
        document.getElementById('totp-conta-issuer').value = account ? (account.issuer || '') : '';
        document.getElementById('totp-conta-label').value = account ? (account.label || '') : '';
        document.getElementById('totp-conta-secret').value = account ? (account.secret || '') : '';
        document.getElementById('totp-conta-digits').value = String(account ? (account.digits || 6) : 6);
        document.getElementById('totp-conta-period').value = String(account ? (account.period || 30) : 30);
        el.contaErro.classList.add('d-none');
        document.getElementById('totp-conta-excluir').classList.toggle('d-none', isNew);
        modalConta().show();
    }

    function aplicarUri() {
        const parsed = parseOtpauth(document.getElementById('totp-conta-uri').value);
        if (!parsed) return;
        if (parsed.issuer) document.getElementById('totp-conta-issuer').value = parsed.issuer;
        if (parsed.label) document.getElementById('totp-conta-label').value = parsed.label;
        if (parsed.secret) document.getElementById('totp-conta-secret').value = parsed.secret;
        document.getElementById('totp-conta-digits').value = String(parsed.digits);
        document.getElementById('totp-conta-period').value = String(parsed.period);
    }

    async function salvarConta() {
        bumpIdle();
        el.contaErro.classList.add('d-none');
        try {
            aplicarUri();
            const id = document.getElementById('totp-conta-id').value;
            const issuer = document.getElementById('totp-conta-issuer').value.trim();
            const label = document.getElementById('totp-conta-label').value.trim();
            const secret = document.getElementById('totp-conta-secret').value.replace(/\s+/g, '').toUpperCase();
            const digits = Number(document.getElementById('totp-conta-digits').value) === 8 ? 8 : 6;
            const period = Math.max(15, Math.min(120, Number(document.getElementById('totp-conta-period').value) || 30));
            if (!secret) throw new Error('Informe o segredo');
            base32Decode(secret);
            // valida gerando um codigo
            await totp(secret, digits, period, Date.now());
            if (!issuer && !label) throw new Error('Informe emissor ou conta');
            const agora = new Date().toISOString();
            const payload = {
                id: id || uuid(),
                issuer,
                label,
                secret,
                digits,
                period,
                atualizado: agora,
            };
            const idx = state.data.accounts.findIndex((e) => e.id === payload.id);
            if (idx >= 0) {
                payload.criado = state.data.accounts[idx].criado || agora;
                state.data.accounts[idx] = payload;
            } else {
                payload.criado = agora;
                state.data.accounts.push(payload);
            }
            await persistir();
            document.getElementById('totp-conta-secret').value = '';
            modalConta().hide();
            await refreshCodes();
            renderAccounts();
        } catch (e) {
            el.contaErro.textContent = e.message || 'Erro ao salvar';
            el.contaErro.classList.remove('d-none');
        }
    }

    async function excluirConta() {
        const id = document.getElementById('totp-conta-id').value;
        if (!id || !confirm('Excluir esta conta?')) return;
        state.data.accounts = state.data.accounts.filter((e) => e.id !== id);
        await persistir();
        document.getElementById('totp-conta-secret').value = '';
        modalConta().hide();
        await refreshCodes();
        renderAccounts();
    }

    async function excluirVault() {
        if (!state.vaultId) return;
        if (!confirm('Excluir este vault permanentemente?')) return;
        const id = state.vaultId;
        lock();
        await api(API + '/' + id, { method: 'DELETE' });
        await carregarLista();
    }

    async function importarArquivo(file) {
        const fd = new FormData();
        fd.append('arquivo', file);
        await api(API + '/importar', { method: 'POST', body: fd });
        await carregarLista();
    }

    document.querySelectorAll('.js-totp-toggle').forEach((btn) => {
        btn.addEventListener('click', () => {
            const inp = document.getElementById(btn.dataset.target);
            if (!inp) return;
            if (inp.type === 'password' || (inp.id === 'totp-conta-secret' && inp.dataset.masked !== '0')) {
                // secret field is text by default; for password fields toggle type
            }
            if (inp.type === 'password') {
                inp.type = 'text';
                btn.innerHTML = '<i class="bi bi-eye-slash"></i>';
            } else if (inp.id !== 'totp-conta-secret') {
                inp.type = 'password';
                btn.innerHTML = '<i class="bi bi-eye"></i>';
            } else {
                // toggle visibility via CSS filter for secret text field
                const hidden = inp.style.webkitTextSecurity === 'disc' || inp.dataset.hide === '1';
                if (hidden) {
                    inp.style.webkitTextSecurity = '';
                    inp.dataset.hide = '0';
                    btn.innerHTML = '<i class="bi bi-eye-slash"></i>';
                } else {
                    inp.style.webkitTextSecurity = 'disc';
                    inp.dataset.hide = '1';
                    btn.innerHTML = '<i class="bi bi-eye"></i>';
                }
            }
        });
    });

    // mask secret by default
    const secretInp = document.getElementById('totp-conta-secret');
    if (secretInp) {
        secretInp.style.webkitTextSecurity = 'disc';
        secretInp.dataset.hide = '1';
    }

    document.getElementById('totp-btn-novo')?.addEventListener('click', () => {
        document.getElementById('totp-novo-nome').value = '';
        document.getElementById('totp-novo-senha').value = '';
        document.getElementById('totp-novo-senha2').value = '';
        el.novoErro.classList.add('d-none');
        renderForca('');
        modalNovo().show();
    });
    document.getElementById('totp-novo-senha')?.addEventListener('input', (e) => renderForca(e.target.value));
    document.getElementById('totp-novo-salvar')?.addEventListener('click', criarVault);
    document.getElementById('totp-unlock-ok')?.addEventListener('click', desbloquear);
    document.getElementById('totp-unlock-senha')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') desbloquear();
    });
    document.getElementById('totp-btn-voltar')?.addEventListener('click', () => {
        lock();
        carregarLista();
    });
    document.getElementById('totp-btn-add')?.addEventListener('click', () => abrirConta(null));
    document.getElementById('totp-conta-uri')?.addEventListener('change', aplicarUri);
    document.getElementById('totp-conta-uri')?.addEventListener('blur', aplicarUri);
    document.getElementById('totp-conta-salvar')?.addEventListener('click', salvarConta);
    document.getElementById('totp-conta-excluir')?.addEventListener('click', excluirConta);
    document.getElementById('totp-btn-excluir-vault')?.addEventListener('click', excluirVault);
    document.getElementById('totp-btn-export')?.addEventListener('click', () => {
        if (state.vaultId) window.location.href = API + '/' + state.vaultId + '/exportar';
    });
    document.getElementById('totp-import-file')?.addEventListener('change', async (e) => {
        const file = e.target.files && e.target.files[0];
        e.target.value = '';
        if (!file) return;
        try { await importarArquivo(file); }
        catch (err) { alert(err.message || 'Falha ao importar'); }
    });
    el.busca?.addEventListener('input', () => {
        bumpIdle();
        renderAccounts();
    });

    ['click', 'keydown', 'mousemove'].forEach((evt) => {
        document.addEventListener(evt, () => {
            if (state.masterPassword) bumpIdle();
        }, { passive: true });
    });

    window.addEventListener('pagehide', () => {
        stopTick();
        state.masterPassword = null;
        state.data = null;
        state.codes = {};
    });

    document.querySelectorAll('.btn-limpar-escopo[data-escopo="totp-auth"]').forEach((btn) => {
        btn.addEventListener('click', () => {
            setTimeout(() => { lock(); carregarLista(); }, 800);
        });
    });

    carregarLista().catch((e) => {
        el.vazio.textContent = e.message || 'Erro ao listar vaults';
        el.vazio.classList.remove('d-none');
    });
})();
