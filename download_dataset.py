#!/usr/bin/env python3
"""Download the deep_code_bench dataset from Hugging Face."""

print("importing...")
from datasets import load_dataset
print("Done importing.")
import os

def download_dataset():
    """Download and cache the Qodo deep_code_bench dataset."""
    print("Downloading deep_code_bench dataset from Hugging Face...")

    # Load the dataset (it will be cached automatically)
    dataset = load_dataset("Qodo/deep_code_bench", split="train")

    print(f"Dataset downloaded successfully!")
    print(f"Total examples in train split: {len(dataset)}")
    print(f"\nDataset features: {dataset.features}")

    # Save the dataset to local directory for easier access
    output_dir = "data/deep_code_bench"
    os.makedirs(output_dir, exist_ok=True)
    dataset.save_to_disk(output_dir)
    print(f"\nDataset saved to: {output_dir}")

    # Print a sample
    print(f"\nFirst example:")
    print(dataset[0])

if __name__ == "__main__":
    download_dataset()
