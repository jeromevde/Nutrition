#%%
import pytesseract
from PIL import Image
import re
import csv

def extract_ticket_info(image_path, output_csv):
    # Extract text from image
    image = Image.open(image_path)
    text = pytesseract.image_to_string(image)

    # Parse text to extract relevant information
    lines = text.split('\n')
    data = []
    for line in lines:
        match = re.match(r'(\d+)\s+(.+?)\s+(\d+,\d+)', line)
        if match:
            barcode, product_name, quantity = match.groups()
            quantity = float(quantity.replace(',', '.'))
            data.append([barcode, quantity, product_name])

    # Save to CSV
    with open(output_csv, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(["Barcode", "Quantity", "Product Name"])
        writer.writerows(data)

    print(f"Data has been saved to {output_csv}")

# Usage
image_path = '/workspaces/nutrition/scrapers/delhaize/tickets/downloaded_image (1).jpg'
output_csv = 'delhaize/ticket_data.csv'
extract_ticket_info(image_path, output_csv)
# %%
