// go to https://www.carrefour.be/nl/frequentlypurchased 
// and execute the following in your console 

// Select all elements with the class 'd-lg-none mobile-name'
const elements = document.querySelectorAll('span.d-lg-none.mobile-name');

// Function to find the brand within the same product tile
function findBrand(element) {
    const productTile = element.closest('.product-tile');
    if (productTile) {
        const brandWrapper = productTile.querySelector('.brand-wrapper a');
        return brandWrapper ? brandWrapper.textContent.trim() : '';
    }
    return '';
}

// Collect the text content of each element into an array with brand prepended
const data = Array.from(elements).map(span => {
    const brand = findBrand(span);
    return [brand + ' - ' + span.textContent];
});

// Convert the array to CSV format
function convertToCSV(arr) {
    return arr.map(row => row.join(',')).join('\n');
}

const csvContent = convertToCSV(data);

// Create Blob and trigger download
const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
const link = document.createElement("a");
if (link.download !== undefined) { // feature detection
    const url = URL.createObjectURL(blob);
    link.setAttribute("href", url);
    link.setAttribute("download", "favorite_items_carrefour.csv");
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}