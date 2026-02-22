#!/usr/bin/env python3
"""
Batch Receipt OCR — Entry Point 1
===================================
Recursively finds all .jpg receipt images in the repo and OCRs them using
OpenRouter's vision API, writing one CSV per image.

Quick start
-----------
    export OPENROUTER_API_KEY="your-key-here"
    pip install openai httpx
    python3 batch_ocr_receipts.py

What it does
------------
- Recursively finds all .jpg files under the repo root
- Skips images that already have a matching .csv file (safe to re-run)
- Processes up to MAX_WORKERS receipts in parallel
- Uses `qwen/qwen-2-vl-7b-instruct` (~50× cheaper than GPT-4o, ~$0.03–0.08
  per 100 receipts) — edit MODEL below to switch

Output
------
Each <image>.jpg gets a matching <image>.csv with columns:
    product_name, price, barcode

Configuration
-------------
Tweak these constants at the top of this file:
    MAX_WORKERS = 10   # parallel requests
    MODEL = "qwen/qwen-2-vl-7b-instruct"

After OCR, run the nutrient analysis pipeline:
    cd nutrient_analysis
    python 01_build_mapping.py   # LLM-maps product names → USDA foods
    python 02_nutrition_report.py  # builds the interactive HTML report
"""

import os
import json
import base64
import csv
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import httpx

# Configuration
MAX_WORKERS = 10  # Number of parallel requests
MODEL = "qwen/qwen-2-vl-7b-instruct"  # Cheapest vision model on OpenRouter

def query_openrouter(image_path, api_key):
    """OCR a receipt image using OpenRouter."""
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    
    prompt = """
You are a receipt OCR system. Extract ALL products from this receipt.

CRITICAL: Return ONLY a valid JSON array, nothing else. No markdown, no explanations.
Format: [{"product_name": "...", "price": "...", "barcode": "..."}, ...]

Rules:
- Extract exact product names as shown on receipt
- Include all items, even if similar/duplicates
- For prices, use format like "3.50" or "1.99" 
- For barcode, use value if visible, otherwise leave empty string ""
- If kg-priced, include unit in product_name like "Apples 1.5kg"
- Return ONLY the JSON array, absolutely nothing else
"""
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                ]
            }
        ],
        "max_tokens": 4000,
        "temperature": 0
    }
    
    client = httpx.Client(timeout=60.0)
    try:
        response = client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload
        )
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"].strip()
    finally:
        client.close()

def parse_and_save(raw_json, csv_path):
    """Parse JSON response and save to CSV."""
    # Strip markdown code blocks if present
    raw_json = raw_json.strip()
    if raw_json.startswith('```'):
        lines = raw_json.split('\n')
        raw_json = '\n'.join(lines[1:-1]) if len(lines) > 2 else raw_json
    raw_json = raw_json.lstrip('`\n json').rstrip('`\n ')
    
    # Try to extract JSON array from text
    import re
    json_match = re.search(r'\[.*\]', raw_json, re.DOTALL)
    if json_match:
        raw_json = json_match.group(0)
    
    # Fix common JSON issues
    raw_json = raw_json.replace('\n', ' ').replace('\r', '')
    raw_json = re.sub(r',\s*]', ']', raw_json)  # Remove trailing commas in arrays
    raw_json = re.sub(r',\s*}', '}', raw_json)  # Remove trailing commas in objects
    
    try:
        data = json.loads(raw_json)
        if not isinstance(data, list):
            data = [data]
    except json.JSONDecodeError as e:
        # Last resort: return empty array to avoid complete failure
        print(f"  ⚠️  Warning: Could not parse JSON properly, saving empty result")
        data = []
    
    # Save to CSV
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["product_name", "price", "barcode"])
        w.writeheader()
        for item in data:
            if isinstance(item, dict):
                # Normalize price format
                if isinstance(item.get('price'), str):
                    item['price'] = item['price'].replace(',', '.')
                w.writerow(item)
    
    return len(data)

def process_receipt(image_path, api_key):
    """Process a single receipt image."""
    csv_path = image_path.with_suffix('.csv')
    
    # Skip if already processed
    if csv_path.exists():
        return None, "skipped"
    
    try:
        start = time.time()
        raw = query_openrouter(image_path, api_key)
        num_items = parse_and_save(raw, csv_path)
        elapsed = time.time() - start
        
        return image_path, {
            "status": "success",
            "items": num_items,
            "time": elapsed
        }
    except Exception as e:
        return image_path, {
            "status": "failed",
            "error": str(e)
        }

def find_all_receipts(root_dir):
    """Recursively find all JPG files."""
    root = Path(root_dir)
    return list(root.rglob("*.jpg")) + list(root.rglob("*.jpeg")) + list(root.rglob("*.JPG"))

def main():
    # Check for API key
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("❌ ERROR: OPENROUTER_API_KEY environment variable not set!")
        print("Get your key from: https://openrouter.ai/keys")
        return 1
    
    # Find all receipts
    print("🔍 Scanning for receipt images...")
    receipts = find_all_receipts(".")
    
    if not receipts:
        print("No JPG files found!")
        return 0
    
    print(f"Found {len(receipts)} images")
    
    # Filter out already processed
    to_process = [r for r in receipts if not r.with_suffix('.csv').exists()]
    already_done = len(receipts) - len(to_process)
    
    if already_done > 0:
        print(f"📋 {already_done} already processed (skipping)")
    
    if not to_process:
        print("✅ All receipts already processed!")
        return 0
    
    print(f"🚀 Processing {len(to_process)} receipts with {MAX_WORKERS} workers...\n")
    
    # Process in parallel
    results = {"success": 0, "failed": 0, "total_items": 0}
    failed_files = []
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_receipt, img, api_key): img for img in to_process}
        
        for i, future in enumerate(as_completed(futures), 1):
            img_path = futures[future]
            result = future.result()
            
            if result[1] == "skipped":
                continue
            
            path, info = result
            rel_path = path.relative_to(".")
            
            if info["status"] == "success":
                results["success"] += 1
                results["total_items"] += info["items"]
                print(f"✓ [{i}/{len(to_process)}] {rel_path} → {info['items']} items ({info['time']:.1f}s)")
            else:
                results["failed"] += 1
                failed_files.append((rel_path, info["error"]))
                print(f"✗ [{i}/{len(to_process)}] {rel_path} → FAILED: {info['error']}")
    
    # Summary
    print(f"\n{'='*60}")
    print(f"📊 SUMMARY")
    print(f"{'='*60}")
    print(f"✅ Processed: {results['success']}")
    print(f"❌ Failed: {results['failed']}")
    print(f"📦 Total items extracted: {results['total_items']}")
    print(f"📋 Already done: {already_done}")
    print(f"🏁 Total receipts: {len(receipts)}")
    
    if failed_files:
        print(f"\n❌ Failed files:")
        for path, error in failed_files:
            print(f"  - {path}: {error}")
    
    return 0 if results['failed'] == 0 else 1

if __name__ == "__main__":
    exit(main())
