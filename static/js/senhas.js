(function () {
    const formAdd = document.getElementById('form-add-senha');
    const lista = document.getElementById('lista-senhas');
    const formProc = document.getElementById('form-processar');
    const modoSelect = document.getElementById('unlock-modo');
    const salvarWrap = document.getElementById('unlock-salvar-wrap');
    const senhasCard = document.getElementById('unlock-senhas-card');
    const wordlistFonte = document.getElementById('wordlist-fonte');
    const wordlistUploadWrap = document.getElementById('wordlist-upload-wrap');

    function atualizarWordlistFonte() {
        if (!wordlistUploadWrap) return;
        const upload = wordlistFonte && wordlistFonte.value === 'upload';
        wordlistUploadWrap.classList.toggle('d-none', !upload);
    }

    function atualizarModo() {
        const modo = (modoSelect && modoSelect.value) || 'salvas';
        document.querySelectorAll('[data-unlock-pane]').forEach((el) => {
            el.classList.toggle('d-none', el.getAttribute('data-unlock-pane') !== modo);
        });
        if (salvarWrap) {
            salvarWrap.classList.toggle('d-none', modo === 'salvas');
        }
        if (senhasCard) {
            senhasCard.classList.toggle('d-none', modo !== 'salvas');
        }
        atualizarWordlistFonte();
    }

    if (modoSelect) {
        modoSelect.addEventListener('change', atualizarModo);
        atualizarModo();
    }
    if (wordlistFonte) {
        wordlistFonte.addEventListener('change', atualizarWordlistFonte);
    }

    if (formProc) {
        formProc.addEventListener('submit', () => {
            setTimeout(async () => {
                try {
                    const resp = await fetch('/api/senhas');
                    const data = await resp.json();
                    if (data.senhas) renderSenhas(data.senhas);
                } catch (_) {}
            }, 800);
        });
    }

    if (!formAdd || !lista) return;

    formAdd.addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = new FormData(formAdd);
        try {
            const resp = await fetch('/api/senhas', { method: 'POST', body: formData });
            const data = await resp.json();
            if (!data.ok) {
                alert(data.msg || 'Erro ao adicionar.');
                return;
            }
            renderSenhas(data.senhas);
            formAdd.reset();
        } catch (err) {
            alert('Erro: ' + err.message);
        }
    });

    lista.addEventListener('click', async (e) => {
        const btn = e.target.closest('.btn-remover-senha');
        if (!btn) return;
        const id = btn.dataset.id;
        if (!confirm('Remover esta senha?')) return;

        try {
            const resp = await fetch(`/api/senhas/${id}/excluir`, { method: 'POST' });
            const data = await resp.json();
            if (data.ok) renderSenhas(data.senhas);
        } catch (err) {
            alert('Erro: ' + err.message);
        }
    });

    function renderSenhas(senhas) {
        if (!senhas.length) {
            lista.innerHTML = '<li class="list-group-item text-secondary text-center">Nenhuma senha cadastrada</li>';
            return;
        }
        lista.innerHTML = senhas.map((s) => `
            <li class="list-group-item d-flex justify-content-between align-items-center" data-id="${s.id}">
                <code>${escapeHtml(s.senha)}</code>
                <button class="btn btn-sm btn-outline-danger btn-remover-senha" data-id="${s.id}" title="Remover">
                    <i class="bi bi-x-lg"></i>
                </button>
            </li>
        `).join('');
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, (c) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));
    }
})();
