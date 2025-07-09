#%%
import openai
import os
import json
import base64
import csv
from PIL import Image

def query_openai(image_path, api_key=None):
    api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not api_key: 
        raise Exception("No OpenAI API key!")
    
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    
    prompt = (
        "Extract date, store, and for each product: name, quantity, unit price, total price, barcode. "
        "Return only valid JSON: {date, store, items:[{product_name, quantity, unit_price, total_price, barcode}], total_amount}. "
        "No markdown, no explanation."
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

def parse_and_save(raw, csv_path="parsed_receipt.csv"):
    raw = raw.strip('`\n ')  # remove markdown if any
    try:
        data = json.loads(raw)
    except Exception:
        print("❌ Could not parse JSON")
        return None
    
    print(f"Date: {data.get('date')}, Store: {data.get('store')}, Total: {data.get('total_amount')}")
    for i, item in enumerate(data.get('items', []), 1):
        print(f"{i}. {item.get('product_name')} | Qty: {item.get('quantity')} | Unit: {item.get('unit_price')} | Total: {item.get('total_price')} | Barcode: {item.get('barcode')}")
    
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["product_name","quantity","unit_price","total_price","barcode"])
        w.writeheader()
        w.writerows(data.get('items', []))
    
    print(f"Saved to {csv_path}")

#%%
import os
# os.environ["OPENAI_API_KEY"] = ""  # Set your OpenAI API key
#%%
raw = query_openai("tickets/downloaded_image (30).jpg")
#%%
parse_and_save(raw)
# %%
