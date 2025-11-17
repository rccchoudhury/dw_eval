#!/usr/bin/env python3
"""
Convert Arrow file to JSON format.
"""
import json
import pyarrow as pa
import pyarrow.ipc as ipc
from pathlib import Path


def convert_arrow_to_json(arrow_file: str, output_file: str = None):
    """
    Convert an Arrow file to JSON format.
    
    Args:
        arrow_file: Path to the .arrow file
        output_file: Optional output JSON file path (defaults to same name with .json)
    """
    arrow_path = Path(arrow_file)
    
    if output_file is None:
        output_file = arrow_path.with_suffix('.json')
    
    print(f"Reading Arrow file: {arrow_file}")
    
    # Try different Arrow reading methods
    table = None
    
    # Method 1: Try IPC file format
    try:
        with pa.memory_map(str(arrow_path), 'r') as source:
            reader = ipc.open_file(source)
            table = reader.read_all()
        print("✓ Read using IPC file format")
    except Exception as e:
        print(f"  IPC file format failed: {e}")
    
    # Method 2: Try IPC stream format
    if table is None:
        try:
            with pa.memory_map(str(arrow_path), 'r') as source:
                reader = ipc.open_stream(source)
                table = reader.read_all()
            print("✓ Read using IPC stream format")
        except Exception as e:
            print(f"  IPC stream format failed: {e}")
    
    # Method 3: Try using datasets library (for HuggingFace datasets)
    if table is None:
        try:
            from datasets import Dataset
            dataset = Dataset.from_file(str(arrow_path))
            table = dataset.data
            print("✓ Read using HuggingFace datasets library")
        except Exception as e:
            print(f"  HuggingFace datasets failed: {e}")
            raise RuntimeError(f"Could not read Arrow file with any method: {arrow_file}")
    
    print(f"Loaded table with {table.num_rows} rows and {table.num_columns} columns")
    print(f"Columns: {table.column_names}")
    
    # Convert to Python dictionaries
    data = table.to_pylist()
    
    # Write to JSON
    print(f"Writing to JSON: {output_file}")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"✓ Successfully converted {len(data)} records to JSON")
    print(f"✓ Output saved to: {output_file}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        arrow_file = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else None
    else:
        # Default to the deep_code_bench Arrow file
        arrow_file = "/home/rchoudhu/deepwiki_eval/data/deep_code_bench/data-00000-of-00001.arrow"
        output_file = "/home/rchoudhu/deepwiki_eval/data/deep_code_bench/deepcodebench.json"
    convert_arrow_to_json(arrow_file, output_file)
