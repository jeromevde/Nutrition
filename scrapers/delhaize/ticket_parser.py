#%%
import pytesseract
from PIL import Image
import openai
import os
import re
import json

# Path to your image file (replace with your JPG or PNG file path)
image_path = "tickets/downloaded_image (16).jpg"  # Update this to your file path

# Open and convert the image to text using OCR
image = Image.open(image_path)
ticket_text = pytesseract.image_to_string(image).replace('\n\n', '\n')

print(ticket_text)

# Prepare prompt for LLM
prompt = f"""
Extract the following information from this receipt text:
- Date of purchase
- For each product: barcode (if present), product name, quantity, price

Return the result as a JSON object with fields:
- date: string
- items: list of objects with keys 'barcode', 'product_name', 'quantity', 'price'

Receipt text:
"""
{ticket_text}
"""
"""

# Call OpenAI API (set your API key in the environment variable OPENAI_API_KEY)
openai.api_key = os.getenv("OPENAI_API_KEY")
response = openai.ChatCompletion.create(
    model="gpt-3.5-turbo",
    messages=[{"role": "user", "content": prompt}],
    temperature=0
)

# Parse and print the result
result = response['choices'][0]['message']['content']
print(result)
try:
    parsed = json.loads(result)
    print(parsed)
except Exception:
    print("Could not parse as JSON. Raw output above.")