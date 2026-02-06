# Batch Receipt OCR

Fast parallel OCR for all receipt images using OpenRouter's cheapest vision model.

## Quick Start

```bash
# Set your API key
export OPENROUTER_API_KEY="your-key-here"

# Install dependencies
pip3 install openai

# Run it!
python3 batch_ocr_receipts.py
```

## What It Does

- 🔍 Recursively finds all `.jpg` files in the repo
- 📋 Skips images that already have a `.csv` file
- 🚀 Processes up to 10 receipts in parallel
- 💰 Uses `qwen/qwen-2-vl-7b-instruct` (~50x cheaper than GPT-4o)
- ✅ Shows progress and summary

## Output

Each `image.jpg` gets a matching `image.csv` with:
- `product_name`
- `price`
- `barcode`

## Cost

~$0.03-0.08 per 100 receipts (~50x cheaper than GPT-4o)

## Configuration

Edit these at the top of `batch_ocr_receipts.py`:
- `MAX_WORKERS = 10` - Number of parallel requests
- `MODEL = "qwen/qwen-2-vl-7b-instruct"` - Which vision model to use
