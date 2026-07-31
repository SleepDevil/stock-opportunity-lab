# A-share search directory

`a_share_symbols.csv` is a lightweight code/name directory used by autocomplete. It intentionally contains no quotes, so a cold FaaS instance can answer stock searches without downloading the full live market snapshot.

Refresh it from the repository root with:

```bash
cd backend
../.venv/bin/python scripts/update_stock_search_directory.py
```
