(function () {
    const grid = document.getElementById('hub-tools-grid');
    if (!grid || typeof Sortable === 'undefined') return;

    let dragging = false;

    Sortable.create(grid, {
        animation: 180,
        draggable: '.hub-tool-col',
        ghostClass: 'hub-tool-ghost',
        chosenClass: 'hub-tool-chosen',
        dragClass: 'hub-tool-drag',
        forceFallback: true,
        fallbackTolerance: 4,
        delay: 80,
        delayOnTouchOnly: true,
        onStart() {
            dragging = true;
        },
        async onEnd() {
            const ordem = [...grid.querySelectorAll('.hub-tool-col')]
                .map((el) => el.dataset.slug)
                .filter(Boolean);
            try {
                await fetch('/api/home/ordem', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ordem }),
                });
            } catch (err) {
                console.error(err);
            }
            setTimeout(() => { dragging = false; }, 50);
        },
    });

    grid.addEventListener('click', (e) => {
        if (!dragging) return;
        const link = e.target.closest('.hub-tool-link');
        if (link) {
            e.preventDefault();
            e.stopPropagation();
        }
    }, true);
})();
