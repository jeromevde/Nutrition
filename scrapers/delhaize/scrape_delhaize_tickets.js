(async function scrapeAllDelhaizeMonthsAndReceiptsFast500ms() {
    const EXPAND_WAIT       = 1200;
    const MODAL_OPEN_WAIT   =  500;    // ← changed to 500 ms as requested
    const MODAL_CLOSE_WAIT  =  600;
    const BETWEEN_RECEIPTS  =  400;

    // Step 1: Expand all collapsed months
    console.log("Expanding all months...");
    const monthToggles = document.querySelectorAll('[data-testid="collapsable-button-toggle"][aria-expanded="false"]');

    if (monthToggles.length > 0) {
        for (const toggle of monthToggles) {
            const monthName = toggle.querySelector('.sc-1no3n19-16')?.textContent.trim() || "unknown";
            console.log(`Expanding: ${monthName}`);
            toggle.scrollIntoView({ block: 'center', behavior: 'instant' });
            toggle.click();
            await new Promise(r => setTimeout(r, EXPAND_WAIT));
        }
        console.log(`Expanded ${monthToggles.length} months. Settling...`);
        await new Promise(r => setTimeout(r, 1500));
    } else {
        console.log("All months already expanded.");
    }

    // Step 2: Collect all receipt rows
    const rows = [...document.querySelectorAll('[data-testid="my-receipts-list-row"]')];
    if (rows.length === 0) {
        console.error("No receipts found after expanding months.");
        return;
    }

    console.log(`Found ${rows.length} receipts. Starting super-fast scrape (500 ms modal wait)...`);

    // Step 3: Process receipts
    for (let i = 0; i < rows.length; i++) {
        const row = rows[i];

        const dateEl = row.querySelector('[data-testid="my-receipts-date"]');
        if (!dateEl) continue;

        const dateText = dateEl.textContent.trim();
        const [dd, mm, yyyy] = dateText.split('/');
        const filename = `${yyyy}-${mm}-${dd}_Delhaize.jpg`;

        const button = row.querySelector('[data-testid="my-receipts-list-button"]');
        if (!button) continue;

        button.scrollIntoView({ block: 'center', behavior: 'instant' });
        button.click();

        await new Promise(r => setTimeout(r, MODAL_OPEN_WAIT));

        let img = document.querySelector('img[src^="data:image/jpeg;base64"]') ||
                  document.querySelector('div[data-testid="modal-main-content"] img') ||
                  document.querySelector('img[alt*="Kasticket" i], img[alt*="kassaticket" i], img[alt*="ticket" i]') ||
                  document.querySelector('[role="dialog"] img[src^="data:image"]');

        if (img?.src?.startsWith('data:image')) {
            const link = document.createElement('a');
            link.href = img.src;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            console.log(`[${i+1}/${rows.length}] Saved ${filename}`);
        } else {
            console.warn(`[${i+1}] No image loaded for ${dateText} (500 ms too short?)`);
        }

        // Close modal
        const closeBtn = 
            document.querySelector('[aria-label*="Sluit"], [aria-label*="Close"], [aria-label*="sluiten"]') ||
            document.querySelector('[role="dialog"] button') ||
            document.querySelector('button.close, .modal-close');

        if (closeBtn) {
            closeBtn.click();
        } else {
            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        }

        await new Promise(r => setTimeout(r, MODAL_CLOSE_WAIT + BETWEEN_RECEIPTS));
    }

    console.log("Scrape finished (very fast mode). Check Downloads folder.");
})();