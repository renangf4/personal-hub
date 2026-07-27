(function () {
    const LABELS = {
        dns: 'DNS',
        whois: 'Whois',
        ip: 'IP / Geo',
        http: 'HTTP / TLS',
        portas: 'Portas',
        ping: 'Ping',
        traceroute: 'Traceroute',
        certificados: 'crt.sh',
        rbl: 'RBL',
        shodan: 'Shodan',
        abuseipdb: 'AbuseIPDB',
        virustotal: 'VirusTotal',
    };

    const ENDPOINTS = {
        dns: '/api/rede/dns',
        whois: '/api/rede/whois',
        ip: '/api/rede/ip',
        http: '/api/rede/http',
        portas: '/api/rede/portas',
        ping: '/api/rede/ping',
        traceroute: '/api/rede/traceroute',
        certificados: '/api/rede/certificados',
        rbl: '/api/rede/rbl',
        shodan: '/api/rede/shodan',
        abuseipdb: '/api/rede/abuseipdb',
        virustotal: '/api/rede/virustotal',
    };

    const alvoEl = document.getElementById('rede-alvo');
    const alvoLabel = document.getElementById('rede-alvo-label');
    const modoEl = document.getElementById('rede-modo');
    const btnTudo = document.getElementById('rede-btn-tudo');
    const btnExport = document.getElementById('rede-btn-export');
    const erroEl = document.getElementById('rede-erro');
    const wrap = document.getElementById('rede-resultados');
    const tabsEl = document.getElementById('rede-tabs');
    const acoesWrap = document.getElementById('rede-acoes');
    const keysWrap = document.getElementById('rede-keys-wrap');
    const btnSalvarKeys = document.getElementById('rede-btn-salvar-keys');

    /** @type {Record<string, any>} */
    let ultimoExport = {};
    /** @type {AbortController | null} */
    let consultaAbort = null;
    let consultaId = 0;

    const LS_MODO = 'rede_lookup_modo';
    const LS_ACOES = 'rede_lookup_acoes_v2';
    const PADRAO_ACOES = {
        dominio: ['dns', 'whois', 'ip', 'http'],
        ip: ['whois', 'ip', 'http', 'portas', 'rbl'],
    };

    function modoAtual() {
        return (modoEl && modoEl.value === 'ip') ? 'ip' : 'dominio';
    }

    function escapeHtml(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));
    }

    function out(id) { return document.getElementById('rede-out-' + id); }
    function pane(id) { return document.getElementById('pane-' + id); }
    function tabBtn(id) { return tabsEl && tabsEl.querySelector('[data-rede-tab="' + id + '"]'); }

    function acaoAtiva(btn) {
        return btn.getAttribute('aria-pressed') === 'true';
    }

    function acaoDisponivelNoModo(btn, modo) {
        const modos = (btn.dataset.redeModos || '').split(',').map((s) => s.trim()).filter(Boolean);
        return modos.includes(modo);
    }

    function atualizarKeysVisiveis() {
        if (!keysWrap) return;
        const ativas = new Set(
            Array.from(document.querySelectorAll('[data-rede-acao][data-rede-key]'))
                .filter((b) => !b.classList.contains('d-none') && acaoAtiva(b))
                .map((b) => b.dataset.redeKey)
        );
        let alguma = false;
        document.querySelectorAll('[data-rede-key-pane]').forEach((el) => {
            const show = ativas.has(el.dataset.redeKeyPane);
            el.classList.toggle('d-none', !show);
            if (show) alguma = true;
        });
        keysWrap.classList.toggle('d-none', !alguma);
    }

    function lerAcoesSalvas() {
        try {
            const raw = localStorage.getItem(LS_ACOES);
            if (!raw) return {};
            const obj = JSON.parse(raw);
            return (obj && typeof obj === 'object') ? obj : {};
        } catch (_) {
            return {};
        }
    }

    function salvarPreferencias() {
        try {
            localStorage.setItem(LS_MODO, modoAtual());
            const all = lerAcoesSalvas();
            all[modoAtual()] = acoesSelecionadas();
            localStorage.setItem(LS_ACOES, JSON.stringify(all));
        } catch (_) {}
    }

    function setAcaoAtiva(btn, on) {
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        btn.classList.toggle('btn-primary', on);
        btn.classList.toggle('btn-outline-primary', !on);
        atualizarKeysVisiveis();
    }

    function acoesSelecionadas() {
        return Array.from(document.querySelectorAll('[data-rede-acao]'))
            .filter((b) => !b.classList.contains('d-none') && acaoAtiva(b))
            .map((b) => b.dataset.redeAcao);
    }

    function aplicarModo() {
        const modo = modoAtual();
        if (alvoLabel) alvoLabel.textContent = modo === 'ip' ? 'Endereco IP' : 'Dominio ou URL';
        if (alvoEl) alvoEl.placeholder = modo === 'ip' ? '8.8.8.8' : 'exemplo.com';

        const salvas = lerAcoesSalvas()[modo];
        const ativas = (Array.isArray(salvas) && salvas.length) ? salvas : (PADRAO_ACOES[modo] || []);
        const set = new Set(ativas);

        document.querySelectorAll('[data-rede-acao]').forEach((btn) => {
            const disponivel = acaoDisponivelNoModo(btn, modo);
            btn.classList.toggle('d-none', !disponivel);
            setAcaoAtiva(btn, disponivel && set.has(btn.dataset.redeAcao));
        });
        atualizarKeysVisiveis();
    }

    if (modoEl) {
        try {
            const m = localStorage.getItem(LS_MODO);
            if (m === 'ip' || m === 'dominio') modoEl.value = m;
        } catch (_) {}
        modoEl.addEventListener('change', () => {
            aplicarModo();
            salvarPreferencias();
        });
    }

    if (acoesWrap) {
        acoesWrap.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-rede-acao]');
            if (!btn || btn.classList.contains('d-none')) return;
            setAcaoAtiva(btn, !acaoAtiva(btn));
            salvarPreferencias();
        });
    }

    function showErro(msg) {
        erroEl.textContent = msg || 'Erro';
        erroEl.classList.remove('d-none');
    }

    function clearErro() {
        erroEl.classList.add('d-none');
        erroEl.textContent = '';
    }

    async function post(path, body, signal) {
        const resp = await fetch(path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
            signal,
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            const detail = data.detail;
            throw new Error(typeof detail === 'string' ? detail : (data.msg || ('HTTP ' + resp.status)));
        }
        return data;
    }

    function montarAbas(acoes) {
        tabsEl.innerHTML = acoes.map((id, i) => `
            <li class="nav-item" role="presentation">
                <button type="button"
                    class="nav-link rede-tab rede-tab--loading${i === 0 ? ' active' : ''}"
                    id="tab-${id}"
                    data-rede-tab="${id}"
                    data-bs-toggle="tab"
                    data-bs-target="#pane-${id}"
                    role="tab"
                    aria-controls="pane-${id}"
                    aria-selected="${i === 0 ? 'true' : 'false'}">
                    <span class="rede-tab__label">${escapeHtml(LABELS[id] || id)}</span>
                    <span class="rede-tab__spin spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>
                    <i class="bi bi-check-lg rede-tab__ok d-none" aria-hidden="true"></i>
                    <i class="bi bi-x-lg rede-tab__err d-none" aria-hidden="true"></i>
                </button>
            </li>
        `).join('');

        Object.keys(ENDPOINTS).forEach((id) => {
            const p = pane(id);
            if (!p) return;
            const ativa = acoes.includes(id);
            p.classList.toggle('d-none', !ativa);
            p.classList.remove('show', 'active');
            const o = out(id);
            if (o) {
                o.innerHTML = ativa
                    ? `<div class="rede-pane-loading text-secondary"><div class="spinner-border spinner-border-sm me-2"></div>Consultando ${escapeHtml(LABELS[id] || id)}...</div>`
                    : '';
            }
        });

        const first = pane(acoes[0]);
        if (first) first.classList.add('show', 'active');
    }

    function setTabEstado(id, estado) {
        const btn = tabBtn(id);
        if (!btn) return;
        btn.classList.remove('rede-tab--loading', 'rede-tab--ok', 'rede-tab--erro');
        const spin = btn.querySelector('.rede-tab__spin');
        const ok = btn.querySelector('.rede-tab__ok');
        const err = btn.querySelector('.rede-tab__err');
        if (spin) spin.classList.toggle('d-none', estado !== 'pendente');
        if (ok) ok.classList.toggle('d-none', estado !== 'ok');
        if (err) err.classList.toggle('d-none', estado !== 'erro');
        if (estado === 'pendente') btn.classList.add('rede-tab--loading');
        if (estado === 'ok') btn.classList.add('rede-tab--ok');
        if (estado === 'erro') btn.classList.add('rede-tab--erro');
    }

    function tabela(linhas) {
        const rows = linhas.filter(([, v]) => v != null && v !== '').map(([k, v]) =>
            `<tr><th>${escapeHtml(k)}</th><td><code>${escapeHtml(String(v))}</code></td></tr>`
        ).join('');
        return `<div class="table-responsive"><table class="table table-sm table-dark align-middle mb-0"><tbody>${rows}</tbody></table></div>`;
    }

    function renderDns(data) {
        const el = out('dns');
        if (!data || !data.ok) {
            el.innerHTML = `<p class="text-danger mb-0">${escapeHtml(data && data.msg ? data.msg : 'Falha')}</p>`;
            return;
        }
        const rows = [];
        const regs = data.registros || {};
        Object.keys(regs).forEach((tipo) => {
            const vals = regs[tipo] || [];
            rows.push(`<tr><th>${escapeHtml(tipo)}</th><td>${vals.length ? `<code>${vals.map(escapeHtml).join('<br>')}</code>` : '<span class="text-secondary">—</span>'}</td></tr>`);
        });
        Object.keys(data.erros || {}).forEach((tipo) => {
            rows.push(`<tr><th>${escapeHtml(tipo)}</th><td class="text-warning">${escapeHtml(data.erros[tipo])}</td></tr>`);
        });
        let emailHtml = '';
        const email = data.email || {};
        if ((email.spf && email.spf.length) || (email.dmarc && email.dmarc.length)) {
            emailHtml = `<h3 class="h6 text-secondary mt-3">E-mail (SPF / DMARC)</h3>${tabela([
                ['SPF', (email.spf || []).join(' | ')],
                ['DMARC', (email.dmarc || []).join(' | ')],
            ])}`;
        }
        el.innerHTML = `<p class="small text-secondary mb-2">Alvo: <code>${escapeHtml(data.alvo)}</code></p>
            <div class="table-responsive"><table class="table table-sm table-dark align-middle mb-0"><tbody>${rows.join('')}</tbody></table></div>${emailHtml}`;
    }

    function renderWhois(data) {
        const el = out('whois');
        if (!data || !data.ok) {
            el.innerHTML = `<p class="text-danger mb-0">${escapeHtml(data && data.msg ? data.msg : 'Falha')}</p>`;
            return;
        }
        const campos = data.campos || {};
        const linhas = Object.keys(campos).map((k) => {
            let v = campos[k];
            if (Array.isArray(v)) v = v.join(', ');
            return [k, v];
        });
        el.innerHTML = `<p class="small text-secondary mb-2">Alvo: <code>${escapeHtml(data.alvo)}</code></p>
            ${tabela(linhas)}
            ${data.texto ? `<pre class="rede-whois-raw mt-3 mb-0 small">${escapeHtml(data.texto)}</pre>` : ''}`;
    }

    function renderIp(data) {
        const el = out('ip');
        if (!data || !data.ok) {
            el.innerHTML = `<p class="text-danger mb-0">${escapeHtml(data && data.msg ? data.msg : 'Falha')}</p>`;
            return;
        }
        const blocos = (data.resultados || []).map((r) => {
            const g = r.geo || {};
            return `<div class="mb-3">${r.geo_erro ? `<p class="text-warning small">${escapeHtml(r.geo_erro)}</p>` : ''}
                ${tabela([
                    ['IP', r.ip], ['Reverso', r.reverso || '—'], ['Pais', g.pais], ['Regiao', g.regiao],
                    ['Cidade', g.cidade], ['ISP', g.isp], ['Org', g.org], ['AS', g.as], ['Fuso', g.fuso],
                    ['Proxy', g.proxy == null ? null : (g.proxy ? 'sim' : 'nao')],
                    ['Hosting', g.hosting == null ? null : (g.hosting ? 'sim' : 'nao')],
                ])}</div>`;
        });
        el.innerHTML = `<p class="small text-secondary mb-2">Alvo: <code>${escapeHtml(data.alvo)}</code></p>${blocos.join('')}`;
    }

    function renderHttp(data) {
        const el = out('http');
        if (!data) {
            el.innerHTML = '<p class="text-danger mb-0">Falha</p>';
            return;
        }
        let httpHtml = '<p class="text-secondary">Sem HTTP</p>';
        if (data.http) {
            if (data.http.erro) {
                httpHtml = `<p class="text-warning">${escapeHtml(data.http.erro)}</p>`;
            } else {
                const hdrs = Object.entries(data.http.headers || {}).map(([k, v]) => [k, v]);
                httpHtml = `${tabela([
                    ['URL final', data.http.url_final],
                    ['Status', data.http.status],
                    ['HTTP', data.http.http_version],
                    ['Redirects', (data.http.redirects || []).join(' → ')],
                ])}<h3 class="h6 text-secondary mt-3">Headers</h3>${tabela(hdrs)}`;
            }
        }
        let tlsHtml = '';
        if (data.tls) {
            if (data.tls.erro) {
                tlsHtml = `<h3 class="h6 text-secondary mt-3">TLS</h3><p class="text-warning">${escapeHtml(data.tls.erro)}</p>`;
            } else {
                const sub = data.tls.subject || {};
                const iss = data.tls.issuer || {};
                tlsHtml = `<h3 class="h6 text-secondary mt-3">TLS</h3>${tabela([
                    ['Versao', data.tls.versao],
                    ['Cipher', data.tls.cipher],
                    ['CN', sub.commonName],
                    ['Issuer', iss.commonName || iss.organizationName],
                    ['Valido de', data.tls.not_before],
                    ['Valido ate', data.tls.not_after],
                    ['SAN', (data.tls.san || []).join(', ')],
                    ['Serial', data.tls.serial],
                ])}`;
            }
        }
        el.innerHTML = `<p class="small text-secondary mb-2">Alvo: <code>${escapeHtml(data.alvo)}</code></p>${httpHtml}${tlsHtml}`;
    }

    function renderPortas(data) {
        const el = out('portas');
        if (!data || !data.ok) {
            el.innerHTML = `<p class="text-danger mb-0">${escapeHtml(data && data.msg ? data.msg : 'Falha')}</p>`;
            return;
        }
        el.innerHTML = `<p class="small text-secondary mb-2">Alvo: <code>${escapeHtml(data.alvo)}</code> → <code>${escapeHtml(data.ip)}</code></p>
            ${tabela([
                ['Abertas', (data.abertas || []).join(', ') || 'nenhuma'],
                ['Testadas', data.testadas],
                ['Fechadas/filtradas', data.fechadas_qtd],
            ])}`;
    }

    function renderCmd(elId, data) {
        const el = out(elId);
        if (!data || (!data.ok && !data.saida)) {
            el.innerHTML = `<p class="text-danger mb-0">${escapeHtml(data && data.msg ? data.msg : 'Falha')}</p>`;
            return;
        }
        el.innerHTML = `<p class="small text-secondary mb-2"><code>${escapeHtml(data.comando || '')}</code></p>
            <pre class="rede-whois-raw mb-0 small">${escapeHtml(data.saida || data.msg || '')}</pre>`;
    }

    function renderCerts(data) {
        const el = out('certificados');
        if (!data || !data.ok) {
            el.innerHTML = `<p class="text-danger mb-0">${escapeHtml(data && data.msg ? data.msg : 'Falha')}</p>`;
            return;
        }
        const rows = (data.itens || []).slice(0, 40).map((i) =>
            `<tr><td><code>${escapeHtml(i.nomes)}</code></td><td class="small">${escapeHtml(i.issuer || '')}</td><td class="small">${escapeHtml(i.not_before || '')}</td></tr>`
        ).join('');
        el.innerHTML = `<p class="small text-secondary mb-2">Alvo: <code>${escapeHtml(data.alvo)}</code>
            · ${data.total_bruto || 0} registros
            ${data.link ? `· <a href="${escapeHtml(data.link)}" target="_blank" rel="noopener">crt.sh</a>` : ''}</p>
            <div class="table-responsive"><table class="table table-sm table-dark align-middle mb-0">
            <thead><tr><th>Nomes</th><th>Issuer</th><th>Desde</th></tr></thead>
            <tbody>${rows || '<tr><td colspan="3" class="text-secondary">Nenhum</td></tr>'}</tbody></table></div>`;
    }

    function renderRbl(data) {
        const el = out('rbl');
        if (!data || !data.ok) {
            el.innerHTML = `<p class="text-danger mb-0">${escapeHtml(data && data.msg ? data.msg : 'Falha')}</p>`;
            return;
        }
        const blocos = (data.resultados || []).map((r) => {
            const rows = (r.listas || []).map((l) => {
                const st = l.listado === true ? 'LISTADO' : l.listado === false ? 'limpo' : 'erro';
                const cls = l.listado === true ? 'text-danger' : l.listado === false ? 'text-success' : 'text-warning';
                return `<tr><th>${escapeHtml(l.lista)}</th><td class="${cls}">${escapeHtml(st)}${l.codigos ? ' (' + escapeHtml(l.codigos.join(', ')) + ')' : ''}${l.erro ? ' — ' + escapeHtml(l.erro) : ''}</td></tr>`;
            }).join('');
            return `<div class="mb-3"><p class="mb-1"><code>${escapeHtml(r.ip)}</code></p>
                <table class="table table-sm table-dark mb-0"><tbody>${rows}</tbody></table></div>`;
        });
        el.innerHTML = `<p class="small text-secondary mb-2">Alvo: <code>${escapeHtml(data.alvo)}</code></p>${blocos.join('')}`;
    }

    function renderShodan(data) {
        const el = out('shodan');
        if (!data || !data.ok) {
            el.innerHTML = `<p class="text-danger mb-0">${escapeHtml(data && data.msg ? data.msg : 'Falha')}</p>`;
            return;
        }
        const blocos = (data.resultados || []).map((r) => {
            if (!r.ok) {
                return `<div class="mb-3"><strong>${escapeHtml(r.ip)}</strong><p class="text-warning mb-0">${escapeHtml(r.msg || '')}</p></div>`;
            }
            const servicos = (r.servicos || []).map((s) => {
                const titulo = [s.porta, s.proto, s.produto, s.versao].filter(Boolean).join(' / ');
                return `<div class="mb-2"><code>${escapeHtml(titulo)}</code>${s.banner ? `<pre class="rede-whois-raw mt-1 mb-0 small">${escapeHtml(s.banner)}</pre>` : ''}</div>`;
            }).join('');
            return `<div class="mb-4">${tabela([
                ['IP', r.ip], ['Org', r.org], ['ISP', r.isp], ['ASN', r.asn], ['OS', r.os],
                ['Pais', r.pais], ['Cidade', r.cidade],
                ['Hostnames', (r.hostnames || []).join(', ')],
                ['Portas', (r.portas || []).join(', ')],
                ['Tags', (r.tags || []).join(', ')],
                ['Vulns', (r.vulns || []).join(', ')],
            ])}${servicos ? '<h3 class="h6 text-secondary mt-2">Servicos</h3>' + servicos : ''}
            ${r.link ? `<a href="${escapeHtml(r.link)}" target="_blank" rel="noopener" class="small">Abrir no Shodan</a>` : ''}</div>`;
        });
        el.innerHTML = `<p class="small text-secondary mb-2">Alvo: <code>${escapeHtml(data.alvo)}</code></p>${blocos.join('')}`;
    }

    function renderAbuse(data) {
        const el = out('abuseipdb');
        if (!data || !data.ok) {
            el.innerHTML = `<p class="text-danger mb-0">${escapeHtml(data && data.msg ? data.msg : 'Falha')}</p>`;
            return;
        }
        const blocos = (data.resultados || []).map((r) => {
            if (!r.ok) return `<p class="text-warning">${escapeHtml(r.ip)}: ${escapeHtml(r.msg || '')}</p>`;
            return `<div class="mb-3">${tabela([
                ['IP', r.ip], ['Score', r.score], ['Reports', r.total_reports],
                ['Pais', r.pais], ['ISP', r.isp], ['Uso', r.uso], ['Dominio', r.dominio],
                ['Whitelist', r.whitelisted == null ? null : (r.whitelisted ? 'sim' : 'nao')],
                ['Ultimo', r.ultimo],
            ])}${r.link ? `<a href="${escapeHtml(r.link)}" target="_blank" rel="noopener" class="small">AbuseIPDB</a>` : ''}</div>`;
        });
        el.innerHTML = `<p class="small text-secondary mb-2">Alvo: <code>${escapeHtml(data.alvo)}</code></p>${blocos.join('')}`;
    }

    function renderVt(data) {
        const el = out('virustotal');
        if (!data || !data.ok) {
            el.innerHTML = `<p class="text-danger mb-0">${escapeHtml(data && data.msg ? data.msg : 'Falha')}</p>`;
            return;
        }
        const s = data.stats || {};
        el.innerHTML = `<p class="small text-secondary mb-2">Alvo: <code>${escapeHtml(data.alvo)}</code>
            ${data.link ? `· <a href="${escapeHtml(data.link)}" target="_blank" rel="noopener">VirusTotal</a>` : ''}</p>
            ${tabela([
                ['Malicious', s.malicious],
                ['Suspicious', s.suspicious],
                ['Harmless', s.harmless],
                ['Undetected', s.undetected],
                ['Reputation', data.reputation],
                ['AS owner', data.as_owner],
                ['Pais', data.country],
            ])}`;
    }

    const RENDERERS = {
        dns: renderDns,
        whois: renderWhois,
        ip: renderIp,
        http: renderHttp,
        portas: renderPortas,
        ping: (d) => renderCmd('ping', d),
        traceroute: (d) => renderCmd('traceroute', d),
        certificados: renderCerts,
        rbl: renderRbl,
        shodan: renderShodan,
        abuseipdb: renderAbuse,
        virustotal: renderVt,
    };

    async function rodar(acoes) {
        const alvo = (alvoEl.value || '').trim();
        if (!alvo) {
            showErro(modoAtual() === 'ip' ? 'Informe um IP' : 'Informe um dominio ou URL');
            return;
        }
        if (modoAtual() === 'ip') {
            const ipOk = /^\d{1,3}(\.\d{1,3}){3}$/.test(alvo) || alvo.includes(':');
            if (!ipOk) {
                showErro('No modo IP, informe um endereco IPv4/IPv6 valido');
                return;
            }
        }
        if (!acoes.length) {
            showErro('Selecione ao menos uma fonte');
            return;
        }

        if (consultaAbort) {
            consultaAbort.abort();
        }
        consultaAbort = new AbortController();
        const signal = consultaAbort.signal;
        const idAtual = ++consultaId;

        clearErro();
        ultimoExport = { alvo, modo: modoAtual(), em: new Date().toISOString(), fontes: {} };

        const alvoAtual = document.getElementById('rede-alvo-atual');
        if (alvoAtual) alvoAtual.textContent = alvo;

        wrap.classList.remove('d-none');
        montarAbas(acoes);
        acoes.forEach((a) => setTabEstado(a, 'pendente'));

        const tasks = acoes.map(async (acao) => {
            try {
                const data = await post(ENDPOINTS[acao], { alvo }, signal);
                if (idAtual !== consultaId) return;
                ultimoExport.fontes[acao] = data;
                if (RENDERERS[acao]) RENDERERS[acao](data);
                setTabEstado(acao, 'ok');
            } catch (e) {
                if (idAtual !== consultaId) return;
                if (e && (e.name === 'AbortError' || signal.aborted)) return;
                ultimoExport.fontes[acao] = { ok: false, msg: e.message };
                const o = out(acao);
                if (o) o.innerHTML = `<p class="text-danger mb-0">${escapeHtml(e.message)}</p>`;
                setTabEstado(acao, 'erro');
            }
        });

        await Promise.all(tasks);
    }

    btnTudo.addEventListener('click', () => rodar(acoesSelecionadas()));
    alvoEl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            rodar(acoesSelecionadas());
        }
    });

    if (btnExport) {
        btnExport.addEventListener('click', () => {
            if (!Object.keys(ultimoExport.fontes || {}).length) {
                showErro('Nenhuma consulta para exportar');
                return;
            }
            const blob = new Blob([JSON.stringify(ultimoExport, null, 2)], { type: 'application/json' });
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = `rede-${(ultimoExport.alvo || 'consulta').replace(/[^\w.-]+/g, '_')}.json`;
            a.click();
            URL.revokeObjectURL(a.href);
        });
    }

    if (btnSalvarKeys) {
        btnSalvarKeys.addEventListener('click', async () => {
            const payload = {};
            document.querySelectorAll('.rede-key-input').forEach((inp) => {
                payload[inp.dataset.key] = inp.value.trim();
            });
            try {
                await post('/api/rede/keys', payload);
                btnSalvarKeys.textContent = 'Salvo';
                setTimeout(() => { btnSalvarKeys.textContent = 'Salvar keys'; }, 1200);
            } catch (e) {
                showErro(e.message);
            }
        });
    }

    aplicarModo();
    salvarPreferencias();

    (async function carregarMeuIp() {
        const el = document.getElementById('rede-meu-ip-valor');
        if (!el) return;
        try {
            const resp = await fetch('/api/rede/meu-ip');
            const data = await resp.json();
            el.textContent = (data.ok && data.ip) ? data.ip : (data.msg || 'indisponivel');
        } catch (_) {
            el.textContent = 'indisponivel';
        }
    })();
})();
