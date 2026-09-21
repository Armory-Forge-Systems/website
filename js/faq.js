// Keep the full answers available when JavaScript is disabled.
(() => {
    const grid = document.querySelector('.faq-grid');
    if (!grid || typeof HTMLDialogElement === 'undefined') return;

    const dialog = document.createElement('dialog');
    dialog.className = 'faq-dialog';
    dialog.setAttribute('aria-labelledby', 'faq-dialog-title');
    dialog.innerHTML = '<button type="button" class="faq-close" autofocus>Close <span aria-hidden="true">×</span></button><h2 id="faq-dialog-title"></h2><div class="faq-dialog-answer"></div>';
    document.body.append(dialog);
    dialog.querySelector('.faq-close').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => {
        if (event.target !== dialog) return;
        const bounds = dialog.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right ||
            event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
    });
    dialog.addEventListener('close', () => document.documentElement.classList.remove('faq-dialog-open'));

    const cards = Array.from(grid.querySelectorAll('.faq-item'), (card, index) => {
        const heading = card.querySelector('h4');
        heading.id = `faq-question-${index + 1}`;
        const answer = document.createElement('div');
        answer.className = 'faq-answer';
        card.querySelectorAll('p').forEach(paragraph => answer.append(paragraph));
        card.append(answer);
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'faq-read-more';
        button.textContent = 'Read full answer +';
        button.setAttribute('aria-haspopup', 'dialog');
        button.setAttribute('aria-label', `Read full answer: ${heading.textContent}`);
        button.addEventListener('click', () => {
            dialog.querySelector('h2').textContent = heading.textContent;
            dialog.querySelector('.faq-dialog-answer').replaceChildren(...Array.from(answer.children, paragraph => paragraph.cloneNode(true)));
            dialog.showModal();
            document.documentElement.classList.add('faq-dialog-open');
        });
        card.append(button);
        return { answer, button };
    });
    grid.classList.add('faq-enhanced');
    const updateOverflow = () => cards.forEach(({ answer, button }) => {
        const truncated = answer.scrollHeight > answer.clientHeight + 1;
        answer.classList.toggle('faq-truncated', truncated);
        button.style.visibility = truncated ? 'visible' : 'hidden';
    });
    new ResizeObserver(updateOverflow).observe(grid);
    document.fonts.ready.then(updateOverflow);
    updateOverflow();
})();
