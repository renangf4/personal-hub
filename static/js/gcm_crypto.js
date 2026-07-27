(function () {
    const FORMAT_VERSION = 1;
    const VERSION_LENGTH = 1;
    const DEFAULT_PBKDF2_ITERATIONS = 210000;
    const MIN_PBKDF2_ITERATIONS = 100000;
    const SALT_LENGTH = 16;
    const IV_LENGTH = 12;
    const KEY_LENGTH = 256;

    async function deriveKey(password, salt, iterations) {
        if (iterations < MIN_PBKDF2_ITERATIONS) {
            throw new Error('PBKDF2 iterations must be at least ' + MIN_PBKDF2_ITERATIONS);
        }
        const encoder = new TextEncoder();
        const passwordKey = await crypto.subtle.importKey(
            'raw',
            encoder.encode(password),
            'PBKDF2',
            false,
            ['deriveBits', 'deriveKey']
        );
        return crypto.subtle.deriveKey(
            { name: 'PBKDF2', salt, iterations, hash: 'SHA-256' },
            passwordKey,
            { name: 'AES-GCM', length: KEY_LENGTH },
            false,
            ['encrypt', 'decrypt']
        );
    }

    function generateRandomBytes(length) {
        return crypto.getRandomValues(new Uint8Array(length));
    }

    function arrayBufferToBase64(buffer) {
        const bytes = new Uint8Array(buffer);
        let binary = '';
        for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
        return btoa(binary);
    }

    function base64ToArrayBuffer(base64) {
        const binary = atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
        return bytes.buffer;
    }

    async function encrypt(plaintext, password, iterations) {
        iterations = iterations || DEFAULT_PBKDF2_ITERATIONS;
        const encoder = new TextEncoder();
        const data = encoder.encode(plaintext);
        const salt = generateRandomBytes(SALT_LENGTH);
        const iv = generateRandomBytes(IV_LENGTH);
        const key = await deriveKey(password, salt, iterations);
        const encryptedData = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, data);
        const combined = new Uint8Array(VERSION_LENGTH + SALT_LENGTH + IV_LENGTH + encryptedData.byteLength);
        combined.set(new Uint8Array([FORMAT_VERSION]), 0);
        combined.set(salt, VERSION_LENGTH);
        combined.set(iv, VERSION_LENGTH + SALT_LENGTH);
        combined.set(new Uint8Array(encryptedData), VERSION_LENGTH + SALT_LENGTH + IV_LENGTH);
        return arrayBufferToBase64(combined.buffer);
    }

    async function decrypt(encryptedBase64, password, iterations) {
        iterations = iterations || DEFAULT_PBKDF2_ITERATIONS;
        const combined = new Uint8Array(base64ToArrayBuffer(encryptedBase64));
        const minLength = VERSION_LENGTH + SALT_LENGTH + IV_LENGTH;
        if (combined.length < minLength) throw new Error('Invalid encrypted data format');
        const version = combined[0];
        if (version !== FORMAT_VERSION) {
            throw new Error('Unsupported format version: ' + version);
        }
        const salt = combined.slice(VERSION_LENGTH, VERSION_LENGTH + SALT_LENGTH);
        const iv = combined.slice(VERSION_LENGTH + SALT_LENGTH, VERSION_LENGTH + SALT_LENGTH + IV_LENGTH);
        const ciphertext = combined.slice(VERSION_LENGTH + SALT_LENGTH + IV_LENGTH);
        const key = await deriveKey(password, salt, iterations);
        try {
            const decryptedData = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, ciphertext);
            return new TextDecoder().decode(decryptedData);
        } catch (error) {
            if (error.name === 'OperationError') {
                throw new Error('Decryption failed: incorrect password or tampered data');
            }
            throw error;
        }
    }

    // Ordem de grandeza: 1 GPU forte vs PBKDF2-HMAC-SHA256 @ 210k iteracoes
    const GUESSES_PER_SEC = 5000;

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
            { lim: 60, div: 1, nome: 'segundo', plural: 'segundos' },
            { lim: 3600, div: 60, nome: 'minuto', plural: 'minutos' },
            { lim: 86400, div: 3600, nome: 'hora', plural: 'horas' },
            { lim: 86400 * 365, div: 86400, nome: 'dia', plural: 'dias' },
            { lim: 86400 * 365 * 100, div: 86400 * 365, nome: 'ano', plural: 'anos' },
            { lim: 86400 * 365 * 1000, div: 86400 * 365 * 100, nome: 'seculo', plural: 'seculos' },
            { lim: Infinity, div: 86400 * 365 * 1e9, nome: 'bilhao de anos', plural: 'bilhoes de anos' },
        ];
        for (const u of units) {
            if (seconds < u.lim) {
                const n = Math.max(1, Math.round(seconds / u.div));
                const label = u.nome.includes('bilhao')
                    ? (n === 1 ? u.nome : u.plural)
                    : (n === 1 ? u.nome : u.plural);
                return '~' + n.toLocaleString('pt-BR') + ' ' + label;
            }
        }
        return 'tempo astronomico';
    }

    function estimateCrack(pass) {
        const len = pass.length;
        if (!len) return null;
        const base = charsetSize(pass);
        // log10(keyspace) = len * log10(base); media = keyspace / (2 * rate)
        const log10Keyspace = len * Math.log10(base);
        const log10Half = log10Keyspace - Math.log10(2);
        const log10Sec = log10Half - Math.log10(GUESSES_PER_SEC);
        let seconds;
        if (log10Sec > 308) seconds = Infinity;
        else seconds = Math.pow(10, log10Sec);

        let nivel;
        let cls;
        if (seconds < 3600) {
            nivel = 'Muito fraca';
            cls = 'alert-danger';
        } else if (seconds < 86400 * 30) {
            nivel = 'Fraca';
            cls = 'alert-danger';
        } else if (seconds < 86400 * 365) {
            nivel = 'Moderada';
            cls = 'alert-warning';
        } else if (seconds < 86400 * 365 * 100) {
            nivel = 'Boa';
            cls = 'alert-success';
        } else {
            nivel = 'Forte';
            cls = 'alert-success';
        }

        return {
            nivel,
            cls,
            html:
                '<strong>' + nivel + '</strong> — brute force offline (~' +
                GUESSES_PER_SEC.toLocaleString('pt-BR') +
                ' tent./s, 1 GPU, PBKDF2 210k): media ' +
                formatDuration(seconds) +
                '. Ataques com dicionario/senhas comuns sao bem mais rapidos.',
        };
    }

    function renderStrength(pass) {
        if (!strength) return;
        const est = estimateCrack(pass);
        if (!est) {
            strength.className = 'alert py-2 px-3 small mb-0 mt-2 d-none';
            strength.innerHTML = '';
            return;
        }
        strength.className = 'alert py-2 px-3 small mb-0 mt-2 ' + est.cls;
        strength.innerHTML = est.html;
    }

    async function copiar(texto, btn) {
        try {
            await navigator.clipboard.writeText(texto);
            const prev = btn.innerHTML;
            btn.innerHTML = '<i class="bi bi-check2"></i>';
            setTimeout(() => { btn.innerHTML = prev; }, 1200);
        } catch (_) {}
    }

    document.querySelectorAll('.gcm-toggle-pass').forEach((btn) => {
        btn.addEventListener('click', () => {
            const inp = document.getElementById(btn.dataset.target);
            if (!inp) return;
            const show = inp.type === 'password';
            inp.type = show ? 'text' : 'password';
            btn.innerHTML = show ? '<i class="bi bi-eye-slash"></i>' : '<i class="bi bi-eye"></i>';
        });
    });

    const passEnc = document.getElementById('gcm-pass-enc');
    const strength = document.getElementById('gcm-pass-strength');
    if (passEnc) {
        passEnc.addEventListener('input', () => renderStrength(passEnc.value));
    }

    document.getElementById('gcm-btn-enc')?.addEventListener('click', async () => {
        const plain = document.getElementById('gcm-plain');
        const pass = document.getElementById('gcm-pass-enc');
        const out = document.getElementById('gcm-enc-out');
        const wrap = document.getElementById('gcm-enc-out-wrap');
        const erro = document.getElementById('gcm-enc-erro');
        erro.classList.add('d-none');
        wrap.classList.add('d-none');
        try {
            if (!plain.value) throw new Error('Informe o texto');
            if (!pass.value) throw new Error('Informe a senha');
            out.value = await encrypt(plain.value, pass.value);
            wrap.classList.remove('d-none');
            pass.value = '';
            renderStrength('');
        } catch (e) {
            erro.textContent = e.message || 'Erro ao criptografar';
            erro.classList.remove('d-none');
        }
    });

    document.getElementById('gcm-btn-dec')?.addEventListener('click', async () => {
        const cipher = document.getElementById('gcm-cipher');
        const pass = document.getElementById('gcm-pass-dec');
        const out = document.getElementById('gcm-dec-out');
        const wrap = document.getElementById('gcm-dec-out-wrap');
        const erro = document.getElementById('gcm-dec-erro');
        erro.classList.add('d-none');
        wrap.classList.add('d-none');
        try {
            if (!cipher.value.trim()) throw new Error('Cole o texto criptografado');
            if (!pass.value) throw new Error('Informe a senha');
            out.value = await decrypt(cipher.value.trim(), pass.value);
            wrap.classList.remove('d-none');
            pass.value = '';
        } catch (e) {
            erro.textContent = e.message || 'Erro ao descriptografar';
            erro.classList.remove('d-none');
        }
    });

    document.getElementById('gcm-btn-copy-enc')?.addEventListener('click', (e) => {
        const out = document.getElementById('gcm-enc-out');
        if (out?.value) copiar(out.value, e.currentTarget);
    });
    document.getElementById('gcm-btn-copy-dec')?.addEventListener('click', (e) => {
        const out = document.getElementById('gcm-dec-out');
        if (out?.value) copiar(out.value, e.currentTarget);
    });
})();
