#!/usr/bin/env python3
"""
Batch Receipt OCR — Entry Point 1
===================================
Recursively finds all .jpg receipt images in the repo and OCRs them using
OpenRouter's vision API, writing one CSV per image.

Quick start
-----------
    # Option A: OpenRouter (set key, then run)
    export OPENROUTER_API_KEY="your-key-here"
    python -m skills.ocr_batch

    # Option B: VS Code Copilot Proxy (no key needed)
    # Install hyorman/copilot-proxy extension, run "Copilot Proxy: Start Server",
    # then just run the script — it auto-detects the local proxy.

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
    python -m skills.build_mapping
    python -m skills.nutrition_report
"""

import os
import sys
import json
import base64
import csv
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import httpx
import openai

from .common import DELHAIZE_SCRAPER_DIR, ROOT_DIR
from .llm_client import make_client

# ── Timestamped logging ───────────────────────────────────────────────────────
_t0 = time.monotonic()
_tprev: list[float] = [_t0]

def tlog(msg: str, end: str = "\n", flush: bool = False) -> None:
    """Print msg prefixed with [HH:MM:SS +step_elapsed / total] for profiling."""
    now   = time.monotonic()
    step  = now - _tprev[0]
    total = now - _t0
    _tprev[0] = now
    ts = time.strftime("%H:%M:%S", time.localtime())
    print(f"[{ts} +{step:5.1f}s / {total:6.1f}s] {msg}", end=end, flush=flush)

REPO_ROOT = ROOT_DIR

# Configuration
MAX_WORKERS = 10  # Number of parallel requests (single-image mode)
MODEL = "qwen/qwen-2-vl-7b-instruct"  # Cheapest vision model on OpenRouter

# Batch mode — group N images per LLM call (set to 1 to disable batching)
BATCH_SIZE = 4  # images per API call (only used with --batch flag)


# ── Single-image OCR (default) ───────────────────────────────────────────────

_OCR_PROMPT = (
    "You are a receipt OCR system. Extract ALL products from this receipt.\n\n"
    "CRITICAL: Return ONLY a valid JSON array, nothing else. No markdown, no explanations.\n"
    'Format: [{"product_name": "...", "price": "...", "barcode": "..."}, ...]\n\n'
    "Rules:\n"
    "- Extract exact product names as shown on receipt\n"
    "- Include all items, even if similar/duplicates\n"
    '- For prices, use format like "3.50" or "1.99"\n'
    '- For barcode, use value if visible, otherwise leave empty string ""\n'
    '- If kg-priced, include unit in product_name like "Apples 1.5kg"\n'
    "- Return ONLY the JSON array, absolutely nothing else"
)


def query_llm(image_path, client: openai.OpenAI, model: str) -> str:
    """OCR a single receipt image via any OpenAI-compatible client."""
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _OCR_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                ],
            }
        ],
        max_tokens=4000,
        temperature=0,
    )
    return resp.choices[0].message.content.strip()

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

def process_receipt(image_path, client: openai.OpenAI, model: str):
    """Process a single receipt image."""
    csv_path = image_path.with_suffix('.csv')
    
    # Skip if already processed
    if csv_path.exists():
        return None, "skipped"
    
    try:
        start = time.time()
        raw = query_llm(image_path, client, model)
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


# ── Batch-image OCR (optional, --batch flag) ────────────────────────────────

def query_openrouter_batch(image_paths: list, api_key: str) -> str:
    """
    Send multiple receipt images in a single multi-modal API call.
    The LLM returns a JSON object keyed by image index.
    """
    content: list[dict] = []
    prompt_text = (
        "You are a receipt OCR system. You will receive MULTIPLE receipt images, "
        f"numbered 0 to {len(image_paths)-1}.\n\n"
        "For EACH image, extract ALL products.\n\n"
        "Return ONLY a valid JSON object (no markdown, no explanation) with this structure:\n"
        '{"0": [{"product_name":"...","price":"...","barcode":"..."},...], '
        '"1": [...], ...}\n\n'
        "Rules:\n"
        "- Use the image index (starting from 0) as the key\n"
        "- Extract exact product names as shown on each receipt\n"
        "- For prices, use format like \"3.50\" or \"1.99\"\n"
        "- For barcode, use value if visible, otherwise \"\"\n"
        "- If kg-priced, include unit in product_name\n"
    )
    content.append({"type": "text", "text": prompt_text})
    for i, path in enumerate(image_paths):
        with open(path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        content.append({"type": "text", "text": f"--- Image {i} ---"})
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
        })

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 4000 * len(image_paths),
        "temperature": 0,
    }

    client = httpx.Client(timeout=120.0)
    try:
        response = client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    finally:
        client.close()


def query_llm_batch(image_paths: list, client: openai.OpenAI, model: str) -> str:
    """OCR multiple receipt images through any OpenAI-compatible client."""
    content: list[dict] = []
    prompt_text = (
        "You are a receipt OCR system. You will receive MULTIPLE receipt images, "
        f"numbered 0 to {len(image_paths)-1}.\n\n"
        "For EACH image, extract ALL products.\n\n"
        "Return ONLY a valid JSON object (no markdown, no explanation) with this structure:\n"
        '{"0": [{"product_name":"...","price":"...","barcode":"..."},...], '
        '"1": [...], ...}\n\n'
        "Rules:\n"
        "- Use the image index (starting from 0) as the key\n"
        "- Extract exact product names as shown on each receipt\n"
        "- For prices, use format like \"3.50\" or \"1.99\"\n"
        "- For barcode, use value if visible, otherwise \"\"\n"
        "- If kg-priced, include unit in product_name\n"
    )
    content.append({"type": "text", "text": prompt_text})
    for i, path in enumerate(image_paths):
        with open(path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()
        content.append({"type": "text", "text": f"--- Image {i} ---"})
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
        })

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        max_tokens=4000 * len(image_paths),
        temperature=0,
    )
    return resp.choices[0].message.content.strip()


def process_batch(image_paths: list, client: openai.OpenAI, model: str) -> dict:
    """
    Process a batch of images in one API call. Returns {path: status_dict}.
    """
    results: dict = {}
    start = time.time()

    try:
        raw = query_llm_batch(image_paths, client, model)
        # Parse outer JSON
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        raw = raw.lstrip("`\n json").rstrip("`\n ")

        import re as _re
        json_match = _re.search(r'\{.*\}', raw, _re.DOTALL)
        if json_match:
            raw = json_match.group(0)

        batch_data = json.loads(raw)
        elapsed = time.time() - start

        for i, path in enumerate(image_paths):
            key = str(i)
            items = batch_data.get(key, [])
            if not isinstance(items, list):
                items = []
            csv_path = path.with_suffix(".csv")
            num = parse_and_save(json.dumps(items), csv_path)
            results[path] = {"status": "success", "items": num, "time": elapsed / len(image_paths)}

    except Exception as e:
        # On failure, mark all as failed
        for path in image_paths:
            results[path] = {"status": "failed", "error": str(e)}

    return results

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Batch OCR receipt images")
    parser.add_argument("--batch", action="store_true",
                        help=f"Send {BATCH_SIZE} images per API call (faster, optional)")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE,
                        help=f"Images per batch (default: {BATCH_SIZE})")
    args = parser.parse_args()

    # Resolve LLM backend (OpenRouter or Copilot Proxy)
    client, model = make_client(MODEL)

    # Find all raw Delhaize receipt images in data/delhaize/.
    tlog("🔍 Scanning for receipt images...")
    receipts = find_all_receipts(DELHAIZE_SCRAPER_DIR)

    if not receipts:
        tlog("No JPG files found!")
        return 0

    tlog(f"Found {len(receipts)} images")

    # Filter out already processed
    to_process = [r for r in receipts if not r.with_suffix('.csv').exists()]
    already_done = len(receipts) - len(to_process)

    if already_done > 0:
        print(f"📋 {already_done} already processed (skipping)")

    if not to_process:
        tlog("✅ All receipts already processed!")
        return 0

    results = {"success": 0, "failed": 0, "total_items": 0}
    failed_files = []

    if args.batch:
        # ── Batch mode: group images into multi-image API calls ──────────────
        bs = args.batch_size
        tlog(f"🚀 Processing {len(to_process)} receipts in batches of {bs}...")
        for batch_start in range(0, len(to_process), bs):
            batch = to_process[batch_start:batch_start + bs]
            batch_num = batch_start // bs + 1
            total_batches = (len(to_process) + bs - 1) // bs
            tlog(f"  Batch {batch_num}/{total_batches} ({len(batch)} images) …", end=" ", flush=True)

            batch_results = process_batch(batch, client, model)
            for path, info in batch_results.items():
                rel_path = path.relative_to(REPO_ROOT)
                if info["status"] == "success":
                    results["success"] += 1
                    results["total_items"] += info["items"]
                else:
                    results["failed"] += 1
                    failed_files.append((rel_path, info.get("error", "unknown")))
            print("done")
    else:
        # ── Single-image mode (default): parallel workers ────────────────────
        tlog(f"🚀 Processing {len(to_process)} receipts with {MAX_WORKERS} workers...")

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(process_receipt, img, client, model): img for img in to_process}

            for i, future in enumerate(as_completed(futures), 1):
                img_path = futures[future]
                result = future.result()

                if result[1] == "skipped":
                    continue

                path, info = result
                rel_path = path.relative_to(REPO_ROOT)

                if info["status"] == "success":
                    results["success"] += 1
                    results["total_items"] += info["items"]
                    tlog(f"✓ [{i}/{len(to_process)}] {rel_path} → {info['items']} items ({info['time']:.1f}s)")
                else:
                    results["failed"] += 1
                    failed_files.append((rel_path, info["error"]))
                    tlog(f"✗ [{i}/{len(to_process)}] {rel_path} → FAILED: {info['error']}")

    # Summary
    tlog(f"\n{'='*60}")
    tlog("📊 SUMMARY")
    tlog(f"{'='*60}")
    tlog(f"✅ Processed: {results['success']}")
    tlog(f"❌ Failed: {results['failed']}")
    tlog(f"📦 Total items extracted: {results['total_items']}")
    tlog(f"📋 Already done: {already_done}")
    tlog(f"🏁 Total receipts: {len(receipts)}")

    if failed_files:
        print(f"\n❌ Failed files:")
        for path, error in failed_files:
            print(f"  - {path}: {error}")

    return 0 if results['failed'] == 0 else 1

if __name__ == "__main__":
    exit(main())
