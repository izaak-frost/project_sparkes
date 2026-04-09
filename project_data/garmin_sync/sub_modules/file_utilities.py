import json
from pathlib import Path


def save_to_json(data: list[dict], record_type:str, output_file: str | Path) -> None:
    """Save data to a JSON file."""
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"    Saved {len(data)} {record_type} to {output_path}\n")