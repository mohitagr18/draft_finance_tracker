"""Bank statement parsing agent implementation."""

from pathlib import Path
from typing import List

from config.constants import OUTPUT_DIR
from utils.file_utils import ensure_output_dir
from utils.data_combiner import combine_parsed_data
from utils.statement_processor import process_single_statement


async def run_parsing_agent(statement_files: List[str]) -> dict:
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
    for i, file_path in enumerate(statement_files, 1):
        filename = Path(file_path).name
        print(f"\n[{i}/{len(statement_files)}] Processing: {filename}")
        
        success, error_msg, parsed_data = await process_single_statement(file_path, OUTPUT_DIR)
        
        if success:
            print(f"✓ Successfully processed: {filename}")
            individual_output_path = Path(OUTPUT_DIR) / f"{Path(file_path).stem}_parsed.json"
            successful_files.append(str(individual_output_path))
        else:
            print(f"✗ Failed to process: {filename}")
            print(f"  Error: {error_msg}")
            failed_files.append((filename, error_msg))
    
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