from __future__ import annotations

from pathlib import Path

import akshare as ak


OUTPUT_PATH = Path(__file__).resolve().parents[1] / "app" / "resources" / "a_share_symbols.csv"


def main() -> None:
    frame = ak.stock_info_a_code_name()[["code", "name"]].copy()
    frame["code"] = frame["code"].astype(str).str.zfill(6)
    frame["name"] = frame["name"].astype(str).str.strip()
    frame = (
        frame[frame["code"].str.fullmatch(r"\d{6}") & frame["name"].ne("")]
        .drop_duplicates(subset=["code"], keep="last")
        .sort_values("code")
        .rename(columns={"code": "代码", "name": "名称"})
    )
    if len(frame) < 4_000:
        raise RuntimeError(f"refusing to replace stock directory with only {len(frame)} rows")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUTPUT_PATH, index=False)
    print(f"wrote {len(frame)} A-share symbols to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
