#%%
import openai
import os
import json
import base64
import csv
from PIL import Image
import os
import re
import random

#%%
def query_openrouter(image_path, api_key=None):
    """
    Use OpenRouter's cheapest vision model for OCR.
    Falls back to qwen/qwen-2-vl-7b-instruct (extremely cheap and effective).
    """
    api_key = api_key or os.getenv("OPENROUTER_API_KEY")
    if not api_key: 
        raise Exception("No OPENROUTER_API_KEY found in environment!")
    
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
        - Ensure quantities, prices, and barcodes are correctly aligned with each product name, accounting for irregular receipt formatting.
        - for items priced in kg, add the kg unit to the quantity
        - Do not include markdown, explanations, or additional text outside the JSON output, no ``` etc ...
        """
    )
    
    # Use OpenRouter with the cheapest vision model
    client = openai.OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
        timeout=60,
        max_retries=2
    )
    
    resp = client.chat.completions.create(
        model="qwen/qwen-2-vl-7b-instruct",  # One of the cheapest vision models
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
    return True

if __name__ == "__main__":
    # Check for API key
    if not os.getenv("OPENROUTER_API_KEY"):
        print("ERROR: OPENROUTER_API_KEY environment variable not set!")
        print("Get your key from: https://openrouter.ai/keys")
        exit(1)
    
    tickets_dir = "tickets"
    tickets = [f for f in os.listdir(tickets_dir) if f.lower().endswith((".jpg", ".jpeg", ".png"))]
    
    print(f"Found {len(tickets)} receipt images")
    
    # Process unprocessed tickets
    processed = 0
    skipped = 0
    failed = 0
    
    random.shuffle(tickets)
    for fname in tickets:
        base, _ = os.path.splitext(fname)
        csv_path = os.path.join(tickets_dir, f"{base}.csv")
        
        if os.path.exists(csv_path):
            skipped += 1
            continue
            
        img_path = os.path.join(tickets_dir, fname)
        print(f"\n{'='*60}")
        print(f"Processing: {fname}")
        print('='*60)
        
        try:
            raw = query_openrouter(img_path)
            if parse_and_save(raw, csv_path, ticket_name=fname):
                processed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"ERROR processing {fname}: {e}")
            failed += 1
    
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"Processed: {processed}")
    print(f"Skipped (already done): {skipped}")
    print(f"Failed: {failed}")
    print(f"Total: {len(tickets)}")
