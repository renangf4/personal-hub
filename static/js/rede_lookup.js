(function () {
    const alvoEl = document.getElementById('rede-alvo');
    const btnTudo = document.getElementById('rede-btn-tudo');
    const statusEl = document.getElementById('rede-status');
    const erroEl = document.getElementById('rede-erro');
    const wrap = document.getElementById('rede-resultados');
    const cardDns = document.getElementById('rede-card-dns');
    const cardWhois = document.getElementById('rede-card-whois');
    const cardIp = document.getElementById('rede-card-ip');
    const cardShodan = document.getElementById('rede-card-shodan');
    const outDns = document.getElementById('rede-out-dns');
    const outWhois = document.getElementById('rede-out-whois');
    const outIp = document.getElementById('rede-out-ip');
    const outShodan = document.getElementById('rede-out-shodan');
    const shodanKeyEl = document.getElementById('rede-shodan-key');
    const btnSalvarShodan = document.getElementById('rede-btn-salvar-shodan');
    const shodanWrap = document.getElementById('rede-shodan-wrap');
    const acoesWrap = document.getElementById('rede-acoes');

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, (c) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));
    }

    function acaoAtiva(btn) {
        return btn.getAttribute('aria-pressed') === 'true';
    }

    function setAcaoAtiva(btn, on) {
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        btn.classList.toggle('btn-primary', on);
        btn.classList.toggle('btn-outline-primary', !on);
        if (btn.dataset.redeAcao === 'shodan' && shodanWrap) {
            shodanWrap.classList.toggle('d-none', !on);
        }
    }

    function acoesSelecionadas() {
        return Array.from(document.querySelectorAll('[data-rede-acao]'))
            .filter(acaoAtiva)
            .map((b) => b.dataset.redeAcao);
    }

    if (acoesWrap) {
        acoesWrap.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-rede-acao]');
            if (!btn) return;
            setAcaoAtiva(btn, !acaoAtiva(btn));
        });
    }

    function setBusy(on) {
        statusEl.classList.toggle('d-none', !on);
        btnTudo.disabled = on;
    }

    function showErro(msg) {
        erroEl.textContent = msg || 'Erro';
        erroEl.classList.remove('d-none');
    }

    function clearErro() {
        erroEl.classList.add('d-none');
        erroEl.textContent = '';
    }

    async function post(path, body) {
        const resp = await fetch(path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            const detail = data.detail;
            throw new Error(typeof detail === 'string' ? detail : (data.msg || ('HTTP ' + resp.status)));
        }
        return data;
    }

    function renderDns(data) {
        if (!data || !data.ok) {
            outDns.innerHTML = `<p class="text-danger mb-0">${escapeHtml(data && data.msg ? data.msg : 'Falha')}</p>`;
            return;
        }
        const rows = [];
        const regs = data.registros || {};
        Object.keys(regs).forEach((tipo) => {
            const vals = regs[tipo] || [];
            if (!vals.length) {
                rows.push(`<tr><th>${escapeHtml(tipo)}</th><td class="text-secondary">—</td></tr>`);
                return;
            }
            rows.push(`<tr><th>${escapeHtml(tipo)}</th><td><code>${vals.map(escapeHtml).join('<br>')}</code></td></tr>`);
        });
        const errs = data.erros || {};
        Object.keys(errs).forEach((tipo) => {
            rows.push(`<tr><th>${escapeHtml(tipo)}</th><td class="text-warning">${escapeHtml(errs[tipo])}</td></tr>`);
        });
        outDns.innerHTML = `
            <p class="small text-secondary mb-2">Alvo: <code>${escapeHtml(data.alvo)}</code></p>
            <div class="table-responsive">
                <table class="table table-sm table-dark align-middle mb-0">
                    <tbody>${rows.join('') || '<tr><td class="text-secondary">Sem registros</td></tr>'}</tbody>
                </table>
            </div>`;
    }

    function renderWhois(data) {
        if (!data || !data.ok) {
            outWhois.innerHTML = `<p class="text-danger mb-0">${escapeHtml(data && data.msg ? data.msg : 'Falha')}</p>`;
            return;
        }
        const campos = data.campos || {};
        const rows = Object.keys(campos).map((k) => {
            let v = campos[k];
            if (Array.isArray(v)) v = v.join(', ');
            return `<tr><th>${escapeHtml(k)}</th><td><code>${escapeHtml(String(v))}</code></td></tr>`;
        });
        let extra = '';
        if (data.texto) {
            extra = `<pre class="rede-whois-raw mt-3 mb-0 small">${escapeHtml(data.texto)}</pre>`;
        }
        outWhois.innerHTML = `
            <p class="small text-secondary mb-2">Alvo: <code>${escapeHtml(data.alvo)}</code></p>
            <div class="table-responsive">
                <table class="table table-sm table-dark align-middle mb-0">
                    <tbody>${rows.join('') || '<tr><td class="text-secondary">Sem campos</td></tr>'}</tbody>
                </table>
            </div>${extra}`;
    }

    function renderIp(data) {
        if (!data || !data.ok) {
            outIp.innerHTML = `<p class="text-danger mb-0">${escapeHtml(data && data.msg ? data.msg : 'Falha')}</p>`;
            return;
        }
        const blocos = (data.resultados || []).map((r) => {
            const geo = r.geo || {};
            const linhas = [
                ['IP', r.ip],
                ['Reverso', r.reverso || '—'],
                ['Pais', geo.pais],
                ['Regiao', geo.regiao],
                ['Cidade', geo.cidade],
                ['ISP', geo.isp],
                ['Org', geo.org],
                ['AS', geo.as],
                ['Fuso', geo.fuso],
                ['Proxy', geo.proxy == null ? null : (geo.proxy ? 'sim' : 'nao')],
                ['Hosting', geo.hosting == null ? null : (geo.hosting ? 'sim' : 'nao')],
            ].filter(([, v]) => v != null && v !== '');
            const rows = linhas.map(([k, v]) =>
                `<tr><th>${escapeHtml(k)}</th><td><code>${escapeHtml(String(v))}</code></td></tr>`
            ).join('');
            const err = r.geo_erro ? `<p class="text-warning small mb-2">${escapeHtml(r.geo_erro)}</p>` : '';
            return `<div class="mb-3">${err}<table class="table table-sm table-dark align-middle mb-0"><tbody>${rows}</tbody></table></div>`;
        });
        outIp.innerHTML = `
            <p class="small text-secondary mb-2">Alvo: <code>${escapeHtml(data.alvo)}</code></p>
            ${blocos.join('') || '<p class="text-secondary mb-0">Sem dados</p>'}`;
    }

    function renderShodan(data) {
        if (!data || !data.ok) {
            outShodan.innerHTML = `<p class="text-danger mb-0">${escapeHtml(data && data.msg ? data.msg : 'Falha')}</p>`;
            return;
        }
        const blocos = (data.resultados || []).map((r) => {
            if (!r.ok) {
                return `<div class="mb-3"><strong>${escapeHtml(r.ip)}</strong>
                    <p class="text-warning mb-0">${escapeHtml(r.msg || 'Sem dados')}</p></div>`;
            }
            const linhas = [
                ['IP', r.ip],
                ['Org', r.org],
                ['ISP', r.isp],
                ['ASN', r.asn],
                ['OS', r.os],
                ['Pais', r.pais],
                ['Cidade', r.cidade],
                ['Hostnames', (r.hostnames || []).join(', ')],
                ['Portas', (r.portas || []).join(', ')],
                ['Tags', (r.tags || []).join(', ')],
                ['Vulns', (r.vulns || []).join(', ')],
                ['Update', r.ultimo_update],
            ].filter(([, v]) => v != null && v !== '');
            const rows = linhas.map(([k, v]) =>
                `<tr><th>${escapeHtml(k)}</th><td><code>${escapeHtml(String(v))}</code></td></tr>`
            ).join('');
            const servicos = (r.servicos || []).map((s) => {
                const titulo = [s.porta, s.proto, s.produto, s.versao].filter(Boolean).join(' / ');
                const banner = s.banner ? `<pre class="rede-whois-raw mt-1 mb-0 small">${escapeHtml(s.banner)}</pre>` : '';
                return `<div class="mb-2"><code>${escapeHtml(titulo)}</code>${banner}</div>`;
            }).join('');
            const link = r.link
                ? `<a href="${escapeHtml(r.link)}" target="_blank" rel="noopener" class="small">Abrir no Shodan</a>`
                : '';
            return `<div class="mb-4">
                <div class="table-responsive mb-2">
                    <table class="table table-sm table-dark align-middle mb-0"><tbody>${rows}</tbody></table>
                </div>
                ${servicos ? `<h3 class="h6 text-secondary">Servicos</h3>${servicos}` : ''}
                ${link}
            </div>`;
        });
        outShodan.innerHTML = `
            <p class="small text-secondary mb-2">Alvo: <code>${escapeHtml(data.alvo)}</code></p>
            ${blocos.join('') || '<p class="text-secondary mb-0">Sem dados</p>'}`;
    }

    async function rodar(acoes) {
        const alvo = (alvoEl.value || '').trim();
        if (!alvo) {
            showErro('Informe um dominio ou IP');
            return;
        }
        if (!acoes.length) {
            showErro('Selecione ao menos uma fonte');
            return;
        }
        clearErro();
        setBusy(true);
        wrap.classList.remove('d-none');
        cardDns.classList.add('d-none');
        cardWhois.classList.add('d-none');
        cardIp.classList.add('d-none');
        cardShodan.classList.add('d-none');

        const querDns = acoes.includes('dns') && !/^\d{1,3}(\.\d{1,3}){3}$/.test(alvo) && !alvo.includes(':');
        const tasks = [];

        try {
            if (querDns) {
                tasks.push(post('/api/rede/dns', { alvo }).then((d) => {
                    cardDns.classList.remove('d-none');
                    renderDns(d);
                }).catch((e) => {
                    cardDns.classList.remove('d-none');
                    outDns.innerHTML = `<p class="text-danger mb-0">${escapeHtml(e.message)}</p>`;
                }));
            }
            if (acoes.includes('whois')) {
                tasks.push(post('/api/rede/whois', { alvo }).then((d) => {
                    cardWhois.classList.remove('d-none');
                    renderWhois(d);
                }).catch((e) => {
                    cardWhois.classList.remove('d-none');
                    outWhois.innerHTML = `<p class="text-danger mb-0">${escapeHtml(e.message)}</p>`;
                }));
            }
            if (acoes.includes('ip')) {
                tasks.push(post('/api/rede/ip', { alvo }).then((d) => {
                    cardIp.classList.remove('d-none');
                    renderIp(d);
                }).catch((e) => {
                    cardIp.classList.remove('d-none');
                    outIp.innerHTML = `<p class="text-danger mb-0">${escapeHtml(e.message)}</p>`;
                }));
            }
            if (acoes.includes('shodan')) {
                tasks.push(post('/api/rede/shodan', { alvo }).then((d) => {
                    cardShodan.classList.remove('d-none');
                    renderShodan(d);
                }).catch((e) => {
                    cardShodan.classList.remove('d-none');
                    outShodan.innerHTML = `<p class="text-danger mb-0">${escapeHtml(e.message)}</p>`;
                }));
            }
            if (!tasks.length && acoes.includes('dns')) {
                showErro('DNS precisa de um dominio (nao IP)');
            }
            await Promise.all(tasks);
        } finally {
            setBusy(false);
        }
    }

    btnTudo.addEventListener('click', () => rodar(acoesSelecionadas()));
    alvoEl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            rodar(acoesSelecionadas());
        }
    });

    if (btnSalvarShodan && shodanKeyEl) {
        btnSalvarShodan.addEventListener('click', async () => {
            try {
                await post('/api/rede/shodan-key', { key: shodanKeyEl.value.trim() });
                btnSalvarShodan.textContent = 'Salvo';
                setTimeout(() => { btnSalvarShodan.textContent = 'Salvar'; }, 1200);
            } catch (e) {
                showErro(e.message);
            }
        });
    }

    (async function carregarMeuIp() {
        const el = document.getElementById('rede-meu-ip-valor');
        if (!el) return;
        try {
            const resp = await fetch('/api/rede/meu-ip');
            const data = await resp.json();
            if (data.ok && data.ip) {
                el.textContent = data.ip;
            } else {
                el.textContent = data.msg || 'indisponivel';
            }
        } catch (_) {
            el.textContent = 'indisponivel';
        }
    })();
})();
