# ICOdrops Scraper

A CLI tool that scrapes project pages from [icodrops.com](https://icodrops.com) and enriches your CSV dataset with additional fields like website URLs, smart contract addresses, fundraising data, and more.

## Quickstart with GitHub Codespaces (recommended)

No local setup needed. Everything is pre-configured.

1. Click the green **"Code"** button on this repo, then **"Codespaces"** > **"Create codespace on main"**
2. Wait for the codespace to build (~30 seconds). Dependencies install automatically.
3. Run the scraper:
   ```bash
   python scrape_icodrops.py input_projects.csv --output enriched_projects.csv
   ```
4. Download the output: right-click `enriched_projects.csv` in the file explorer > **Download**

That's it. Skip to [Input file format](#input-file-format) for details on preparing your CSV.

---

## Local setup (alternative)

If you prefer to run locally instead of Codespaces:

### 1. Python 3.9+

**Check if you have Python installed:**

```bash
python3 --version
```

If not installed:

- **macOS** (using Homebrew):
  ```bash
  # Install Homebrew if you don't have it
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

  # Install Python
  brew install python
  ```

- **macOS** (without Homebrew):
  Download the installer from https://www.python.org/downloads/macos/

- **Windows**:
  Download the installer from https://www.python.org/downloads/windows/
  During installation, check **"Add Python to PATH"**.

- **Linux (Ubuntu/Debian)**:
  ```bash
  sudo apt update
  sudo apt install python3 python3-pip
  ```

### 2. Clone the repo and install dependencies

```bash
git clone https://github.com/edevardHvide/icodrops-scraper.git
cd icodrops-scraper
pip3 install -r requirements.txt
```

### 3. Run the scraper

```bash
python3 scrape_icodrops.py input_projects.csv --output enriched_projects.csv
```

---

## Input file format

The scraper expects a CSV file with at minimum a `source_url` column containing ICOdrops project page URLs. Example:

```csv
project,symbol,source_url
Elastos,ELA,https://icodrops.com/elastos/
Unitas,UP,https://icodrops.com/unitas/
```

All original columns are preserved in the output. The `source_url` column name is case-insensitive.

If you have an Excel file (.xlsx), export it as CSV first:
- **Excel**: File > Save As > CSV UTF-8
- **Google Sheets**: File > Download > Comma-separated values (.csv)

## Usage

### Basic run

```bash
python3 scrape_icodrops.py input_projects.csv
```

This produces `enriched_projects.csv` in the current directory.

### Custom output file

```bash
python3 scrape_icodrops.py input_projects.csv --output my_output.csv
```

### Adjust concurrency

Default is 5 concurrent workers. For large datasets you can increase this:

```bash
python3 scrape_icodrops.py input_projects.csv --workers 10
```

Keep it at 5-10 to avoid being rate-limited by the server.

### All options

```
python3 scrape_icodrops.py <input_csv> [--output <path>] [--workers <n>]

Arguments:
  input_csv             Path to input CSV with source_url column

Options:
  --output, -o          Output CSV path (default: enriched_projects.csv)
  --workers, -w         Number of concurrent workers (default: 5)
```

## Output

The output CSV contains all original columns plus these scraped fields:

| Column | Source | Description |
|--------|--------|-------------|
| `website_url` | Project links | Project website URL |
| `whitepaper_url` | Project links | Whitepaper/docs URL |
| `twitter_url` | Project links | Twitter/X profile URL |
| `github_url` | Project links | GitHub organization/repo URL |
| `eth_smart_contract_address` | Project links | Ethereum contract address (from etherscan link) |
| `other_smart_contract_address_list` | Project links | Other chain addresses, semicolon-separated |
| `activity_count` | Past Activities | Number of fundraising rounds/activities |
| `tge_distribution_date` | Past Activities | Token Generation Event date |
| `investor_count` | Overview | Number of listed investors |
| `total_raised` | Overview | Total amount raised across all rounds |
| `investing_round_count` | Overview | Number of investing rounds |
| `fdv` | Overview | Fully Diluted Valuation |
| `ecosystems_list` | Overview | Blockchain ecosystems, semicolon-separated |

Fields that are not available on the project page are labeled `MISSING`.

## Resume / caching

The scraper saves results to `_scrape_cache.json` after each run. If interrupted or re-run:

- URLs already in the cache are skipped (instant)
- Only new/missing URLs are scraped

To force a full re-scrape, delete the cache:

```bash
rm _scrape_cache.json
```

## Example

```
Loaded 9 projects from input_projects.csv
Cache has 0 previously scraped URLs (0 rows already cached)
Need to scrape: 8 unique URLs
Workers: 5
Output: enriched_projects.csv

  [1/8] OK  https://icodrops.com/midnight-2/  (0.9/s, ~8s left)
  [2/8] OK  https://icodrops.com/katana/  (1.8/s, ~3s left)
  ...

Done in 4.6s. Wrote 9 rows to enriched_projects.csv
```

## Performance

| URLs | Workers | Estimated time |
|------|---------|---------------|
| 100 | 5 | ~1-2 min |
| 500 | 5 | ~5-7 min |
| 2000 | 5 | ~12-15 min |
| 2000 | 10 | ~7-10 min |

## Troubleshooting

**`ModuleNotFoundError: No module named 'bs4'`**
Run `pip install -r requirements.txt`

**Scraper returns MISSING for fields that exist on the page**
The site may have updated its HTML structure. Open an issue with the project URL.

**Connection errors or timeouts**
Re-run the script. The cache ensures already-scraped URLs are not re-fetched.

**Rate limiting (HTTP 429)**
Reduce workers: `--workers 2`
