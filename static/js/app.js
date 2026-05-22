(function () {
    const form = document.getElementById('form-processar');
    const status = document.getElementById('status');
    const wrap = document.getElementById('resultados-wrap');
    const lista = document.getElementById('resultados');

    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const slug = form.dataset.slug;
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

    const btnLimpar = document.getElementById('btn-limpar-agora');
    const labelLimpar = document.getElementById('btn-limpar-label');

    async function atualizarLabelLixo() {
        if (!labelLimpar) return;
        try {
            const resp = await fetch('/api/limpar-info');
            const info = await resp.json();
            if (info.arquivos > 0) {
                labelLimpar.textContent = `Limpar Lixo (${formatBytes(info.bytes)})`;
            } else {
                labelLimpar.textContent = 'Limpar Lixo';
            }
        } catch (err) {
            labelLimpar.textContent = 'Limpar Lixo';
        }
    }

    window.atualizarLabelLixo = atualizarLabelLixo;
    atualizarLabelLixo();

    if (btnLimpar) {
        btnLimpar.addEventListener('click', async () => {
            btnLimpar.disabled = true;
            try {
                const infoResp = await fetch('/api/limpar-info');
                const info = await infoResp.json();

                if (!info.arquivos) {
                    alert('Nada para limpar. Sem arquivos em cache.');
                    return;
                }

                const msg = `Remover ${info.arquivos} arquivo(s) (${formatBytes(info.bytes)}) do cache?`;
                if (!confirm(msg)) return;

                const resp = await fetch('/api/limpar-agora', { method: 'POST' });
                const data = await resp.json();
                alert(`${data.arquivos} arquivo(s) removido(s) (${formatBytes(data.bytes)} liberados).`);
            } catch (err) {
                alert('Erro ao limpar: ' + err.message);
            } finally {
                btnLimpar.disabled = false;
                atualizarLabelLixo();
            }
        });
    }
})();
