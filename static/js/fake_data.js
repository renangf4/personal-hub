(function () {
    'use strict';

    const API = '/api/fake';
    const IDLE_MS = 15 * 60 * 1000;
    const GUESSES_PER_SEC = 5000;

    const FIELDS = [
        { key: 'apelido', label: 'Apelido / pseudonimo', col: 6 },
        { key: 'nome', label: 'Nome completo', col: 6 },
        { key: 'email', label: 'E-mail', col: 6 },
        { key: 'usuario', label: 'Usuario', col: 6 },
        { key: 'senha', label: 'Senha', col: 6 },
        { key: 'telefone', label: 'Telefone', col: 6 },
        { key: 'cpf', label: 'CPF', col: 6 },
        { key: 'rg', label: 'RG', col: 6 },
        { key: 'nascimento', label: 'Nascimento', col: 6 },
        { key: 'empresa', label: 'Empresa', col: 6 },
        { key: 'cargo', label: 'Cargo', col: 6 },
        { key: 'endereco', label: 'Endereco', col: 12 },
        { key: 'cidade', label: 'Cidade', col: 4 },
        { key: 'uf', label: 'UF', col: 2 },
        { key: 'cep', label: 'CEP', col: 6 },
        { key: 'notas', label: 'Notas', col: 12, textarea: true },
    ];

    const NOMES = [
        'Ana', 'Bruno', 'Carla', 'Diego', 'Elena', 'Felipe', 'Gabriela', 'Henrique',
        'Isabela', 'Joao', 'Karina', 'Lucas', 'Marina', 'Nicolas', 'Olivia', 'Pedro',
        'Rafaela', 'Samuel', 'Tatiana', 'Victor', 'Camila', 'Eduardo', 'Fernanda', 'Gustavo',
        'Helena', 'Igor', 'Julia', 'Kevin', 'Larissa', 'Mateus', 'Natalia', 'Otavio',
        'Patricia', 'Renan', 'Sofia', 'Thiago', 'Ursula', 'Vinicius', 'Yasmin', 'Arthur',
    ];
    const SOBRENOMES = [
        'Silva', 'Santos', 'Oliveira', 'Souza', 'Rodrigues', 'Ferreira', 'Alves', 'Pereira',
        'Lima', 'Gomes', 'Costa', 'Ribeiro', 'Martins', 'Carvalho', 'Almeida', 'Lopes',
        'Soares', 'Fernandes', 'Vieira', 'Barbosa', 'Rocha', 'Dias', 'Nunes', 'Mendes',
        'Cardoso', 'Teixeira', 'Araujo', 'Cavalcanti', 'Moreira', 'Nascimento',
    ];
    const APELIDOS = [
        'nebuloso', 'pixelado', 'ventoazul', 'foxnight', 'orbit', 'cacto', 'luna',
        'corvo', 'maple', 'zeta', 'kiwi', 'nimbus', 'ember', 'quartz', 'delta',
        'nova', 'echo', 'raven', 'sage', 'volt', 'prism', 'harbor', 'drift',
    ];
    const RUAS = [
        'Rua das Flores', 'Av. Brasil', 'Rua Sao Paulo', 'Rua das Palmeiras', 'Av. Paulista',
        'Rua XV de Novembro', 'Rua Dom Pedro II', 'Av. Getulio Vargas', 'Rua Bahia',
        'Rua das Acacias', 'Travessa do Sol', 'Rua Marechal Deodoro', 'Av. Atlantica',
        'Rua das Laranjeiras', 'Rua Sete de Setembro',
    ];
    const BAIRROS = [
        'Centro', 'Jardim America', 'Vila Nova', 'Boa Vista', 'Santa Lucia',
        'Copacabana', 'Liberdade', 'Savassi', 'Batel', 'Moema', 'Pinheiros',
        'Barra', 'Floresta', 'Cidade Jardim',
    ];
    const CIDADES = [
        { cidade: 'Sao Paulo', uf: 'SP' },
        { cidade: 'Rio de Janeiro', uf: 'RJ' },
        { cidade: 'Belo Horizonte', uf: 'MG' },
        { cidade: 'Curitiba', uf: 'PR' },
        { cidade: 'Porto Alegre', uf: 'RS' },
        { cidade: 'Brasilia', uf: 'DF' },
        { cidade: 'Salvador', uf: 'BA' },
        { cidade: 'Recife', uf: 'PE' },
        { cidade: 'Fortaleza', uf: 'CE' },
        { cidade: 'Florianopolis', uf: 'SC' },
        { cidade: 'Campinas', uf: 'SP' },
        { cidade: 'Goiania', uf: 'GO' },
    ];
    const EMPRESAS = [
        'Tech Norte LTDA', 'Solucoes Atlas', 'Nova Orbital', 'Pixel Labs', 'Verde Campo SA',
        'Horizon Soft', 'Data Ponte', 'Lumina Digital', 'Costa & Filhos', 'Aurora Systems',
    ];
    const CARGOS = [
        'Analista', 'Desenvolvedor', 'Designer', 'Gerente de Projetos', 'QA',
        'Product Owner', 'Suporte', 'Estagiario', 'Coordenador', 'Consultor',
    ];
    const DOMINIOS = ['exemplo.com', 'mail.test', 'fake.dev', 'demo.local', 'temp.br'];

    const state = {
        vaultId: null,
        nome: null,
        masterPassword: null,
        data: null,
        pendingId: null,
        pendingNome: null,
        idleTimer: null,
    };

    const el = {
        lista: document.getElementById('fake-view-lista'),
        aberto: document.getElementById('fake-view-aberto'),
        grid: document.getElementById('fake-grid'),
        vazio: document.getElementById('fake-vazio'),
        titulo: document.getElementById('fake-titulo'),
        profiles: document.getElementById('fake-profiles'),
        profilesVazio: document.getElementById('fake-profiles-vazio'),
        busca: document.getElementById('fake-busca'),
        novoForca: document.getElementById('fake-novo-forca'),
        novoErro: document.getElementById('fake-novo-erro'),
        unlockErro: document.getElementById('fake-unlock-erro'),
        perfilErro: document.getElementById('fake-perfil-erro'),
        campos: document.getElementById('fake-perfil-campos'),
    };

    const modalNovo = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('fake-modal-novo'));
    const modalUnlock = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('fake-modal-unlock'));
    const modalPerfil = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('fake-modal-perfil'));

    function pick(arr) {
        return arr[crypto.getRandomValues(new Uint8Array(1))[0] % arr.length];
    }

    function randInt(min, max) {
        const range = max - min + 1;
        const bytes = crypto.getRandomValues(new Uint32Array(1))[0];
        return min + (bytes % range);
    }

    function pad(n, len) {
        return String(n).padStart(len, '0');
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
        try { return new Date(iso).toLocaleString('pt-BR'); } catch (_) { return iso; }
    }

    function cpfCheck(base9) {
        let s = 0;
        for (let i = 0; i < 9; i++) s += Number(base9[i]) * (10 - i);
        let d1 = (s * 10) % 11;
        if (d1 === 10) d1 = 0;
        s = 0;
        const base10 = base9 + String(d1);
        for (let i = 0; i < 10; i++) s += Number(base10[i]) * (11 - i);
        let d2 = (s * 10) % 11;
        if (d2 === 10) d2 = 0;
        return String(d1) + String(d2);
    }

    function gerarCpf() {
        let base = '';
        for (let i = 0; i < 9; i++) base += String(randInt(0, 9));
        const dig = cpfCheck(base);
        const full = base + dig;
        return full.replace(/(\d{3})(\d{3})(\d{3})(\d{2})/, '$1.$2.$3-$4');
    }

    function gerarCep() {
        return pad(randInt(10000, 99999), 5) + '-' + pad(randInt(0, 999), 3);
    }

    function gerarTelefone() {
        const ddd = pick([11, 21, 31, 41, 47, 48, 51, 61, 71, 81, 85]);
        return '(' + ddd + ') 9' + pad(randInt(1000, 9999), 4) + '-' + pad(randInt(1000, 9999), 4);
    }

    function gerarRg() {
        return pad(randInt(10, 99), 2) + '.' + pad(randInt(100, 999), 3) + '.' +
            pad(randInt(100, 999), 3) + '-' + randInt(0, 9);
    }

    function gerarNascimento() {
        const y = randInt(1975, 2004);
        const m = randInt(1, 12);
        const d = randInt(1, 28);
        return pad(d, 2) + '/' + pad(m, 2) + '/' + y;
    }

    function gerarSenha(len) {
        len = len || 16;
        const chars = 'abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$%&*';
        const bytes = crypto.getRandomValues(new Uint8Array(len));
        let out = '';
        for (let i = 0; i < len; i++) out += chars[bytes[i] % chars.length];
        return out;
    }

    function slugify(s) {
        return String(s || '')
            .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
            .toLowerCase().replace(/[^a-z0-9]+/g, '.')
            .replace(/^\.+|\.+$/g, '');
    }

    function gerarCampo(key, ctx) {
        ctx = ctx || {};
        switch (key) {
            case 'apelido':
                return pick(APELIDOS) + randInt(10, 99);
            case 'nome': {
                const n = pick(NOMES);
                const s1 = pick(SOBRENOMES);
                let s2 = pick(SOBRENOMES);
                if (s2 === s1) s2 = pick(SOBRENOMES);
                return n + ' ' + s1 + ' ' + s2;
            }
            case 'email': {
                const base = slugify(ctx.usuario || ctx.apelido || pick(APELIDOS) + randInt(10, 99));
                return base + '@' + pick(DOMINIOS);
            }
            case 'usuario': {
                const first = slugify((ctx.nome || pick(NOMES)).split(' ')[0]);
                return first + '.' + pick(APELIDOS).slice(0, 4) + randInt(1, 99);
            }
            case 'senha': return gerarSenha(16);
            case 'telefone': return gerarTelefone();
            case 'cpf': return gerarCpf();
            case 'rg': return gerarRg();
            case 'nascimento': return gerarNascimento();
            case 'empresa': return pick(EMPRESAS);
            case 'cargo': return pick(CARGOS);
            case 'endereco': {
                return pick(RUAS) + ', ' + randInt(10, 1999) + ' — ' + pick(BAIRROS);
            }
            case 'cidade': return (ctx._loc || pick(CIDADES)).cidade;
            case 'uf': return (ctx._loc || pick(CIDADES)).uf;
            case 'cep': return gerarCep();
            case 'notas': return '';
            default: return '';
        }
    }

    function gerarPerfil() {
        const loc = pick(CIDADES);
        const apelido = gerarCampo('apelido');
        const nome = gerarCampo('nome');
        const usuario = gerarCampo('usuario', { nome, apelido });
        const email = gerarCampo('email', { usuario, apelido });
        return {
            id: uuid(),
            apelido,
            nome,
            email,
            usuario,
            senha: gerarCampo('senha'),
            telefone: gerarCampo('telefone'),
            cpf: gerarCampo('cpf'),
            rg: gerarCampo('rg'),
            nascimento: gerarCampo('nascimento'),
            empresa: gerarCampo('empresa'),
            cargo: gerarCampo('cargo'),
            endereco: gerarCampo('endereco'),
            cidade: loc.cidade,
            uf: loc.uf,
            cep: gerarCampo('cep'),
            notas: '',
            criado: new Date().toISOString(),
            atualizado: new Date().toISOString(),
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

    function lock() {
        state.masterPassword = null;
        state.data = null;
        state.vaultId = null;
        state.nome = null;
        clearIdle();
        el.aberto.classList.add('d-none');
        el.lista.classList.remove('d-none');
        el.profiles.innerHTML = '';
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
                '<div class="cofre-card__icon"><i class="bi bi-person-vcard"></i></div>' +
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
        document.getElementById('fake-unlock-nome').textContent = nome;
        document.getElementById('fake-unlock-senha').value = '';
        el.unlockErro.classList.add('d-none');
        modalUnlock().show();
        setTimeout(() => document.getElementById('fake-unlock-senha').focus(), 300);
    }

    async function desbloquear() {
        const senha = document.getElementById('fake-unlock-senha').value;
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
            if (!data || data.v !== 1 || !Array.isArray(data.profiles)) {
                throw new Error('Conteudo invalido');
            }
            document.getElementById('fake-unlock-senha').value = '';
            state.vaultId = remote.id;
            state.nome = remote.nome;
            state.masterPassword = senha;
            state.data = data;
            state.pendingId = null;
            modalUnlock().hide();
            mostrarAberto();
            bumpIdle();
        } catch (_) {
            document.getElementById('fake-unlock-senha').value = '';
            el.unlockErro.textContent = 'Senha incorreta ou arquivo adulterado';
            el.unlockErro.classList.remove('d-none');
        }
    }

    function mostrarAberto() {
        el.lista.classList.add('d-none');
        el.aberto.classList.remove('d-none');
        el.titulo.textContent = state.nome;
        renderProfiles();
    }

    function renderProfiles() {
        const q = (el.busca.value || '').trim().toLowerCase();
        const list = (state.data.profiles || []).filter((p) => {
            if (!q) return true;
            return FIELDS.map((f) => p[f.key]).join(' ').toLowerCase().includes(q);
        }).slice().sort((a, b) => (a.apelido || a.nome || '').localeCompare(b.apelido || b.nome || '', 'pt'));

        el.profiles.innerHTML = '';
        if (!list.length) {
            el.profilesVazio.classList.remove('d-none');
            return;
        }
        el.profilesVazio.classList.add('d-none');
        list.forEach((p) => {
            const row = document.createElement('div');
            row.className = 'fake-profile';
            const meta = [p.nome, p.email, p.cpf].filter(Boolean).map(escapeHtml).join(' · ');
            row.innerHTML =
                '<div>' +
                '<div class="fake-profile__apelido">' + escapeHtml(p.apelido || p.nome || 'Sem apelido') + '</div>' +
                '<div class="fake-profile__meta">' + meta + '</div>' +
                '</div>' +
                '<div class="fake-profile__acoes">' +
                '<button type="button" class="btn btn-sm btn-outline-secondary" data-act="copy-email" title="Copiar e-mail"><i class="bi bi-envelope"></i></button>' +
                '<button type="button" class="btn btn-sm btn-outline-primary" data-act="copy-json" title="Copiar JSON"><i class="bi bi-braces"></i></button>' +
                '<button type="button" class="btn btn-sm btn-outline-secondary" data-act="edit" title="Editar"><i class="bi bi-pencil"></i></button>' +
                '<button type="button" class="btn btn-sm btn-outline-danger" data-act="del" title="Excluir"><i class="bi bi-trash3"></i></button>' +
                '</div>';
            row.querySelector('[data-act="copy-email"]').addEventListener('click', () => copiar(p.email || '', row.querySelector('[data-act="copy-email"]')));
            row.querySelector('[data-act="copy-json"]').addEventListener('click', () => {
                const clone = { ...p };
                delete clone.id;
                delete clone.criado;
                delete clone.atualizado;
                copiar(JSON.stringify(clone, null, 2), row.querySelector('[data-act="copy-json"]'));
            });
            row.querySelector('[data-act="edit"]').addEventListener('click', () => abrirPerfil(p));
            row.querySelector('[data-act="del"]').addEventListener('click', () => excluirPerfil(p.id));
            el.profiles.appendChild(row);
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
            throw new Error('Colecao nao desbloqueada');
        }
        const blob = await HubGcm.encrypt(JSON.stringify(state.data), state.masterPassword);
        await api(API + '/' + state.vaultId, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ blob }),
        });
        bumpIdle();
    }

    async function criarColecao() {
        const nome = document.getElementById('fake-novo-nome').value.trim();
        const senha = document.getElementById('fake-novo-senha').value;
        const senha2 = document.getElementById('fake-novo-senha2').value;
        el.novoErro.classList.add('d-none');
        try {
            if (!nome) throw new Error('Informe um nome');
            if (!senha) throw new Error('Informe a senha-mestra');
            if (senha !== senha2) throw new Error('As senhas nao coincidem');
            const est = estimateCrack(senha);
            if (est && est.seconds < 86400 * 30) {
                throw new Error('Senha-mestra fraca demais. Use mais caracteres e variedade.');
            }
            const data = { v: 1, profiles: [] };
            const blob = await HubGcm.encrypt(JSON.stringify(data), senha);
            const created = await api(API, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ nome, blob }),
            });
            document.getElementById('fake-novo-senha').value = '';
            document.getElementById('fake-novo-senha2').value = '';
            document.getElementById('fake-novo-nome').value = '';
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

    function buildCampos(perfil) {
        el.campos.innerHTML = '';
        FIELDS.forEach((f) => {
            const col = document.createElement('div');
            col.className = 'col-md-' + f.col;
            const val = perfil ? (perfil[f.key] || '') : '';
            if (f.textarea) {
                col.innerHTML =
                    '<label class="form-label" for="fake-f-' + f.key + '">' + escapeHtml(f.label) + '</label>' +
                    '<textarea class="form-control" id="fake-f-' + f.key + '" rows="2">' + escapeHtml(val) + '</textarea>';
            } else {
                col.innerHTML =
                    '<label class="form-label" for="fake-f-' + f.key + '">' + escapeHtml(f.label) + '</label>' +
                    '<div class="fake-field-row">' +
                    '<input type="text" class="form-control" id="fake-f-' + f.key + '" value="' + escapeHtml(val) + '" autocomplete="off">' +
                    '<button type="button" class="btn btn-outline-secondary" data-regen="' + f.key + '" title="Gerar de novo"><i class="bi bi-shuffle"></i></button>' +
                    '</div>';
            }
            el.campos.appendChild(col);
        });
        el.campos.querySelectorAll('[data-regen]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const key = btn.getAttribute('data-regen');
                const ctx = lerCampos();
                if (key === 'cidade' || key === 'uf') {
                    const loc = pick(CIDADES);
                    document.getElementById('fake-f-cidade').value = loc.cidade;
                    document.getElementById('fake-f-uf').value = loc.uf;
                    return;
                }
                document.getElementById('fake-f-' + key).value = gerarCampo(key, ctx);
            });
        });
    }

    function lerCampos() {
        const out = {};
        FIELDS.forEach((f) => {
            const node = document.getElementById('fake-f-' + f.key);
            out[f.key] = node ? node.value : '';
        });
        return out;
    }

    function abrirPerfil(perfil) {
        bumpIdle();
        const isNew = !perfil;
        document.getElementById('fake-perfil-titulo-modal').textContent = isNew ? 'Novo perfil' : 'Editar perfil';
        document.getElementById('fake-perfil-id').value = perfil ? perfil.id : '';
        buildCampos(perfil || gerarPerfil());
        if (isNew && !perfil) {
            // buildCampos already filled from gerarPerfil in call site — when isNew we pass generated
        }
        el.perfilErro.classList.add('d-none');
        document.getElementById('fake-perfil-excluir').classList.toggle('d-none', isNew);
        modalPerfil().show();
    }

    async function gerarEAbrir() {
        bumpIdle();
        const p = gerarPerfil();
        document.getElementById('fake-perfil-titulo-modal').textContent = 'Novo perfil';
        document.getElementById('fake-perfil-id').value = '';
        buildCampos(p);
        el.perfilErro.classList.add('d-none');
        document.getElementById('fake-perfil-excluir').classList.add('d-none');
        modalPerfil().show();
    }

    async function salvarPerfil() {
        bumpIdle();
        el.perfilErro.classList.add('d-none');
        try {
            const id = document.getElementById('fake-perfil-id').value;
            const campos = lerCampos();
            if (!(campos.apelido || campos.nome)) throw new Error('Informe apelido ou nome');
            const agora = new Date().toISOString();
            const payload = {
                id: id || uuid(),
                ...campos,
                atualizado: agora,
            };
            const idx = state.data.profiles.findIndex((e) => e.id === payload.id);
            if (idx >= 0) {
                payload.criado = state.data.profiles[idx].criado || agora;
                state.data.profiles[idx] = payload;
            } else {
                payload.criado = agora;
                state.data.profiles.push(payload);
            }
            await persistir();
            modalPerfil().hide();
            renderProfiles();
        } catch (e) {
            el.perfilErro.textContent = e.message || 'Erro ao salvar';
            el.perfilErro.classList.remove('d-none');
        }
    }

    async function excluirPerfil(idOpt) {
        const id = idOpt || document.getElementById('fake-perfil-id').value;
        if (!id || !confirm('Excluir este perfil?')) return;
        state.data.profiles = state.data.profiles.filter((e) => e.id !== id);
        await persistir();
        const modalEl = document.getElementById('fake-modal-perfil');
        if (modalEl && modalEl.classList.contains('show')) modalPerfil().hide();
        renderProfiles();
    }

    async function excluirColecao() {
        if (!state.vaultId) return;
        if (!confirm('Excluir esta colecao permanentemente?')) return;
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

    document.querySelectorAll('.js-fake-toggle').forEach((btn) => {
        btn.addEventListener('click', () => {
            const inp = document.getElementById(btn.dataset.target);
            if (!inp) return;
            const show = inp.type === 'password';
            inp.type = show ? 'text' : 'password';
            btn.innerHTML = show ? '<i class="bi bi-eye-slash"></i>' : '<i class="bi bi-eye"></i>';
        });
    });

    document.getElementById('fake-btn-novo')?.addEventListener('click', () => {
        document.getElementById('fake-novo-nome').value = '';
        document.getElementById('fake-novo-senha').value = '';
        document.getElementById('fake-novo-senha2').value = '';
        el.novoErro.classList.add('d-none');
        renderForca('');
        modalNovo().show();
    });
    document.getElementById('fake-novo-senha')?.addEventListener('input', (e) => renderForca(e.target.value));
    document.getElementById('fake-novo-salvar')?.addEventListener('click', criarColecao);
    document.getElementById('fake-unlock-ok')?.addEventListener('click', desbloquear);
    document.getElementById('fake-unlock-senha')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') desbloquear();
    });
    document.getElementById('fake-btn-voltar')?.addEventListener('click', () => {
        lock();
        carregarLista();
    });
    document.getElementById('fake-btn-gerar')?.addEventListener('click', gerarEAbrir);
    document.getElementById('fake-perfil-salvar')?.addEventListener('click', salvarPerfil);
    document.getElementById('fake-perfil-excluir')?.addEventListener('click', () => excluirPerfil());
    document.getElementById('fake-btn-excluir-colecao')?.addEventListener('click', excluirColecao);
    document.getElementById('fake-btn-export')?.addEventListener('click', () => {
        if (state.vaultId) window.location.href = API + '/' + state.vaultId + '/exportar';
    });
    document.getElementById('fake-import-file')?.addEventListener('change', async (e) => {
        const file = e.target.files && e.target.files[0];
        e.target.value = '';
        if (!file) return;
        try { await importarArquivo(file); }
        catch (err) { alert(err.message || 'Falha ao importar'); }
    });
    el.busca?.addEventListener('input', () => {
        bumpIdle();
        renderProfiles();
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

    document.querySelectorAll('.btn-limpar-escopo[data-escopo="fake-data"]').forEach((btn) => {
        btn.addEventListener('click', () => {
            setTimeout(() => { lock(); carregarLista(); }, 800);
        });
    });

    carregarLista().catch((e) => {
        el.vazio.textContent = e.message || 'Erro ao listar colecoes';
        el.vazio.classList.remove('d-none');
    });
})();
