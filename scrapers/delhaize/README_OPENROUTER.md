# OpenRouter OCR for Receipts

This script uses OpenRouter's cheapest vision model (`qwen/qwen-2-vl-7b-instruct`) to perform OCR on receipt images.

## Cost Comparison

- **Old (gpt-4o)**: ~$15-30 per 1000 receipts
- **New (Qwen 2 VL 7B)**: ~$0.30-0.80 per 1000 receipts

**~50x cheaper!** 🎉

## Setup

1. Get an OpenRouter API key: https://openrouter.ai/keys

2. Set the environment variable:
   ```bash
   export OPENROUTER_API_KEY="your-key-here"
   ```

3. Install dependencies:
   ```bash
   pip3 install openai pillow
   ```

## Usage

```bash
cd scrapers/delhaize
python3 parse_delhaize_tickets_openrouter.py
```

The script will:
- Find all `.jpg`/`.jpeg`/`.png` files in the `tickets/` directory
- Skip any that already have a `.csv` file
- Process each receipt and save results to `{filename}.csv`
- Show a summary at the end

## Output Format

Same as the original script - CSV with columns:
- `product_name`
- `price`
- `barcode`

## Notes

- Uses `qwen/qwen-2-vl-7b-instruct` by default (one of the cheapest vision models on OpenRouter)
- Has retry logic built in (max 2 retries)
- Processes receipts in random order
- Prints progress for each receipt
