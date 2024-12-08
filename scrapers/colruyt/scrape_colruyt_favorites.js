// Select all product card elements
const cards = document.querySelectorAll('a.card.card--article');

// Function to extract product name and weight
function extractProductInfo(card) {
    const nameElement = card.querySelector('.card__text');
    const weightElement = card.querySelector('.card__quantity');
    
    const name = nameElement ? nameElement.textContent.trim() : '';
    const weight = weightElement ? weightElement.textContent.trim() : '';
    
    return `${name} - ${weight}`;
}

// Collect product information into an array
const data = Array.from(cards).map(card => [extractProductInfo(card)]);

// Convert the array to CSV format
function convertToCSV(arr) {
    const headers = ['Product Information'];
    const rows = arr.map(row => row.join(',')).join('\n');
    return headers.join(',') + '\n' + rows;
}

const csvContent = convertToCSV(data);

// Create Blob and trigger download
const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
const link = document.createElement("a");
if (link.download !== undefined) { // feature detection
    const url = URL.createObjectURL(blob);
    link.setAttribute("href", url);
    link.setAttribute("download", "favorite_items_colruyt.csv");
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}