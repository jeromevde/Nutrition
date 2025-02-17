function clickButtonsSequentially() {
    const buttons = document.querySelectorAll('[data-testid="my-receipts-list-button"]');
    if (buttons.length > 0) {
        let index = 0;

        function clickNextButton() {
            if (index < buttons.length) {
                const button = buttons[index];
                button.click();
                console.log(`Button ${index + 1} clicked`);

                setTimeout(() => {
                    downloadImage(button);
                    index++;
                    clickNextButton();
                }, 2000);
            }
        }

        clickNextButton();
    } else {
        console.log("No buttons found.");
    }
}

function downloadImage(button) {
    const receiptElement = button.closest('td');
    const dateElement = receiptElement.querySelector('[data-testid="my-receipts-date"]');
    
    if (!dateElement) {
        console.log("Date not found.");
        return;
    }

    const dateParts = dateElement.innerText.trim().split('/');
    const formattedDate = `${dateParts[2]}_${dateParts[1]}_${dateParts[0]}`;
    const image = document.querySelector('div.sc-kaqqtw-0.kWUNdE img');
    
    if (image && image.src.startsWith('data:image')) {
        const a = document.createElement('a');
        a.href = image.src;
        a.download = `${formattedDate}.jpg`;
        a.click();
        console.log(`Image downloaded as ${formattedDate}.jpg`);
    } else {
        console.log("Image not found or not in base64 format.");
    }
}

clickButtonsSequentially();
