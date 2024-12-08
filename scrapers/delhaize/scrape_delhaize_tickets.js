// Function to click buttons one after another

// go to https://www.delhaize.be/nl/my-account/loyalty/tickets

// and then execute this in the console

function clickButtonsSequentially() {
    // Select all buttons with the 'data-testid' attribute 'my-receipts-list-button'
    const buttons = document.querySelectorAll('[data-testid="my-receipts-list-button"]');
    
    // If buttons are found
    if (buttons.length > 0) {
        let index = 0;

        // Function to handle the click and proceed to the next button
        function clickNextButton() {
            if (index < buttons.length) {
                // Click the current button
                buttons[index].click();
                console.log(`Button ${index + 1} clicked`);

                // Increment index to move to the next button
                index++;

                // Simulate delay for the next button click (optional, to wait for the UI to respond)
                setTimeout(clickNextButton, 2000); // Adjust time if needed
                downloadImage();
            }
        }

        // Start clicking the first button
        clickNextButton();
    } else {
        console.log("No buttons found.");
    }
}

// Function to download the image
function downloadImage() {
    // Select the image element
    const image = document.querySelector('div.sc-kaqqtw-0.kWUNdE img');
    
    if (image && image.src.startsWith('data:image')) {
        // Create a temporary anchor element to download the image
        const a = document.createElement('a');
        a.href = image.src;
        a.download = 'downloaded_image.jpg';  // Specify the filename

        // Trigger the download
        a.click();
        console.log("Image downloaded.");
    } else {
        console.log("Image not found or not in base64 format.");
    }
}

// Call the function to start the process
clickButtonsSequentially();

