from pathlib import Path
import pandas as pd

PATH = Path("data/raw/gdelt_articles.parquet")


def main() -> None:
    if not PATH.exists():
        raise FileNotFoundError(
            f"{PATH} does not exist yet. Run the collector first."
        )

    df = pd.read_parquet(PATH)

    print("\n=== DATASET SHAPE ===")
    print(df.shape)

    print("\n=== COLUMN TYPES ===")
    print(df.dtypes)

    print("\n=== MISSING VALUES ===")
    print(df.isna().sum())

    print("\n=== UNIQUE PUBLISHERS ===")
    print(df["publisher_domain"].nunique())

    print("\n=== TOP 10 PUBLISHERS ===")
    print(df["publisher_domain"].value_counts().head(10))

    print("\n=== SAMPLE ===")
    print(df.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
