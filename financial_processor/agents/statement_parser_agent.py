"""Bank statement parsing agent implementation."""

from pathlib import Path
from typing import List
import asyncio

from config.constants import OUTPUT_DIR
from utils.file_utils import ensure_output_dir
from utils.data_combiner import combine_parsed_data
from utils.statement_processor import process_single_statement


async def run_parsing_agent(statement_files: List[str], max_retries: int = 0) -> dict:
    """Process multiple statement files."""
    
    if not statement_files:
        print(f"No statement files provided for parsing.")
        return {}
    
    print(f"Found {len(statement_files)} statement file(s): {statement_files}")
    
    # Ensure output directory exists
    ensure_output_dir(OUTPUT_DIR)
    
    successful_files = []
    failed_files = []
    
    # Process each file
    # Retry settings (tweak as needed)
    MAX_RETRIES = 2      # Total attempts per file = MAX_RETRIES + 1
    RETRY_BACKOFF_SEC = 0.8  # Wait between attempts

    for i, file_path in enumerate(statement_files, 1):
        filename = Path(file_path).name
        print(f"\n[{i}/{len(statement_files)}] Processing: {filename}")

        last_error = None
        success = False

        for attempt in range(0, MAX_RETRIES + 1):
            # Determine strictness level: 0=strict, 1=normal, 2=relaxed
            mode = "strict" if attempt == 0 else ("normal" if attempt == 1 else "relaxed")
            print(f"    - Attempt {attempt + 1}/{MAX_RETRIES + 1} (quality gate: {mode})")

            # Pass the current attempt number to the processor
            success, error_msg, parsed_data = await process_single_statement(
                file_path, OUTPUT_DIR, retry_level=attempt
            )

            if success:
                print(f"✓ Successfully processed: {filename} (attempt {attempt + 1})")
                individual_output_path = Path(OUTPUT_DIR) / f"{Path(file_path).stem}_parsed.json"
                successful_files.append(str(individual_output_path))
                break  # Exit retry loop on success

            last_error = error_msg or "Unknown error"
            print(f"    × Attempt {attempt + 1} failed: {last_error}")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_BACKOFF_SEC)

        if not success:
            print(f"✗ Failed to process after {MAX_RETRIES + 1} attempt(s): {filename}")
            print(f"  Last error: {last_error}")
            failed_files.append((filename, last_error))

    # for i, file_path in enumerate(statement_files, 1):
    #     filename = Path(file_path).name
    #     print(f"\n[{i}/{len(statement_files)}] Processing: {filename}")
        
    #     success, error_msg, parsed_data = await process_single_statement(file_path, OUTPUT_DIR)
        
    #     if success:
    #         print(f"✓ Successfully processed: {filename}")
    #         individual_output_path = Path(OUTPUT_DIR) / f"{Path(file_path).stem}_parsed.json"
    #         successful_files.append(str(individual_output_path))
    #     else:
    #         print(f"✗ Failed to process: {filename}")
    #         print(f"  Error: {error_msg}")
    #         failed_files.append((filename, error_msg))
    
    # Print summary
    print(f"\n=== Processing Summary ===")
    print(f"Total files: {len(statement_files)}")
    print(f"Successful: {len(successful_files)}")
    print(f"Failed: {len(failed_files)}")
    
    if failed_files:
        print("\nFailed files:")
        for filename, error in failed_files:
            print(f"  - {filename}: {error}")
    
    if successful_files:
        print(f"\nCombining {len(successful_files)} successful results...")
        combined_data = combine_parsed_data(successful_files)
        return combined_data
    else:
        print("No files were successfully processed.")
        return {}