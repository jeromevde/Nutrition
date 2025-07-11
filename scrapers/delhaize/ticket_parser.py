#%%
import openai
import os
import json
import base64
import csv
from PIL import Image
import os
import re

def query_openai(image_path, api_key=None):
    api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not api_key: 
        raise Exception("No OpenAI API key!")
    
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    
    prompt = ("""
        Extract date, store, and for each product: name, price, barcode. 
        Return only valid JSON: [{product_name, price, barcode}]
        No markdown, no explanation
        Follow these rules:
        - Extract product names exactly as they appear on the receipt, preserving original spelling and avoiding substitutions
            for example do not replace "hummus" with "CHOUX"
            for example do not replace HET TRAAGSTE BROOD with HET TRADGSTE BROOD
            for example, don't forget a HET TRAAGSTE BROOD ! even if a "NUTRI-BOOST" item was added in between the barcode and product item
        - Ignore non-product terms like "NUTRI-BOOST"
        - Capture all repeated products individually, even if they have identical names, prices, or barcodes.
        - Ensure quantities, prices, and barcodes are correctly aligned with each product name, accounting for irregular receipt formatting.$
        - for items priced in kg, add the kg unit to the quantity
        - Do not include markdown, explanations, or additional text outside the JSON output, no ``` etc ...
        """
    )
    
    client = openai.OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
        ]}],
        max_tokens=4000, 
        temperature=0
    )
    
    return resp.choices[0].message.content.strip()

def parse_and_save(raw, csv_path="parsed_receipt.csv", ticket_name=None):
    raw = raw.lstrip('`\n json') if raw else raw  # one-line fix for leading junk "json" tag
    try:
        data = json.loads(raw)
    except Exception:
        print(f"Could not parse JSON for {ticket_name or csv_path}, below the raw markdown :")
        print(raw)
        return None
    
    # Only print and save the minimal info: product_name, price, barcode
    for i, item in enumerate(data, 1):
        price = item.get('price')
        if isinstance(price, str):
            price = price.replace(',', '.')
        print(f"{i}. {item.get('product_name')} | Price: {price} | Barcode: {item.get('barcode')}")
    
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["product_name","price","barcode"])
        w.writeheader()
        for item in data:
            if isinstance(item['price'], str):
                item['price'] = item['price'].replace(',', '.')
            w.writerow(item)
    
    print(f"Saved to {csv_path}")


os.environ["OPENAI_API_KEY"] = ""  # Set your OpenAI API key


if __name__ == "__main__":
    tickets_dir = "tickets"
    for fname in os.listdir(tickets_dir):
        if fname.lower().endswith((".jpg", ".jpeg", ".png")):
            base, _ = os.path.splitext(fname)
            csv_path = os.path.join(tickets_dir, f"{base}.csv")
            if os.path.exists(csv_path):
                continue
            img_path = os.path.join(tickets_dir, fname)
            try:
                raw = query_openai(img_path)
                parse_and_save(raw, csv_path, ticket_name=fname)
            except Exception as e:
                print(f"Error processing {fname}: {e}")
