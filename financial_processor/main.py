#!/usr/bin/env python3
"""
Complete Financial Statement Processing Pipeline
Entry point for the financial processing system.

Usage:
    python main.py --input-dir /path/to/pdfs --question "Analyze spending patterns"
    python main.py --input-dir /path/to/pdfs --question "What is total spending on Food & Dining?"
"""

import asyncio
import argparse
import json
import shutil
import sys
import traceback
from pathlib import Path
from dotenv import load_dotenv

# Import our modular components
from config.models import validate_api_keys
from config.constants import TEMP_DIR, FINAL_OUTPUT_DIR, OUTPUT_DIR, COMBINED_JSON_FILE
from agents.pdf_converter_agent import convert_pdfs_in_dir
from agents.statement_parser_agent import run_parsing_agent
from agents.data_analyzer_agent import run_data_analyzer
from utils.file_utils import ensure_directories

# Load environment variables
load_dotenv()


async def run_complete_pipeline(input_pdf_dir: str, user_question: str):
    """
    Run the complete pipeline:
    1. Convert PDFs to text files
    2. Parse bank statements to JSON
    3. Generate reports based on user question
    """
    
    print("=" * 80)
    print("🏦 FINANCIAL STATEMENT PROCESSING PIPELINE")
    print("=" * 80)
    print(f"📁 Input Directory: {input_pdf_dir}")
    print(f"❓ User Question: {user_question}")
    print("=" * 80)
    
    # STEP 1: Convert PDFs to text files
    print("\n🔄 STEP 1: Converting PDFs to text files...")
    print("-" * 50)
    
    text_files = convert_pdfs_in_dir(input_pdf_dir, TEMP_DIR)
    
    if not text_files:
        print("❌ No PDF files were successfully converted. Pipeline stopped.")
        return
    
    print(f"✅ Successfully converted {len(text_files)} PDF files to text")
    for file in text_files:
        print(f"   - {file}")
    
    # STEP 2: Parse bank statements to JSON
    print("\n🔄 STEP 2: Parsing bank statements...")
    print("-" * 50)
    
    parsed_data = await run_parsing_agent(text_files)
    
    if not parsed_data:
        print("❌ No bank statements were successfully parsed. Pipeline stopped.")
        return
    
    # Save the combined JSON data
    combined_json_path = COMBINED_JSON_FILE
    with open(combined_json_path, "w", encoding="utf-8") as f:
        json.dump(parsed_data, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Successfully parsed and combined bank statements")
    print(f"   - Combined data saved to: {combined_json_path}")
    print(f"   - Total files processed: {parsed_data.get('combined_summary', {}).get('total_files_processed', 0)}")
    print(f"   - Total transactions: {parsed_data.get('combined_summary', {}).get('total_transactions', 0)}")
    
    # STEP 3: Generate reports based on user question
    print("\n🔄 STEP 3: Analyzing data and generating insights...")
    print("-" * 50)
    
    await run_data_analyzer(combined_json_path, user_question)
    
    print("\n" + "=" * 80)
    print("🎉 PIPELINE COMPLETE!")
    print("=" * 80)
    print("📋 SUMMARY:")
    print(f"   - PDFs processed: {len(text_files)}")
    print(f"   - Statements parsed: {parsed_data.get('combined_summary', {}).get('total_files_processed', 0)}")
    print(f"   - Total transactions: {parsed_data.get('combined_summary', {}).get('total_transactions', 0)}")
    print(f"   - Combined data: {combined_json_path}")
    
    # Check final output
    final_output_path = Path(FINAL_OUTPUT_DIR)
    if final_output_path.exists():
        reports = list(final_output_path.glob("*.md"))
        charts = list(final_output_path.glob("*.png"))
        if reports or charts:
            print(f"   - Analysis output: {final_output_path}/")
            if reports:
                print(f"     • {len(reports)} report(s)")
            if charts:
                print(f"     • {len(charts)} chart(s)")
    
    print("=" * 80)


def main():
    """Main function to handle command line arguments and run the pipeline."""
    global TEMP_DIR, FINAL_OUTPUT_DIR, OUTPUT_DIR
    
    parser = argparse.ArgumentParser(
        description="Complete Financial Statement Processing Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --input-dir /path/to/pdfs --question "Analyze spending patterns"
  python main.py --input-dir ./statements --question "What is total spending on Food & Dining?"
  python main.py --input-dir ./bank_pdfs --question "Who spent the most money?"
        """
    )
    
    parser.add_argument(
        "--input-dir", 
        required=True,
        help="Path to the directory containing PDF bank statements"
    )
    parser.add_argument(
        "--question",
        required=True,
        help="Question to ask about the financial data (use quotes for multi-word questions)"
    )
    parser.add_argument(
        "--temp-dir",
        default=TEMP_DIR,
        help=f"Temporary directory for intermediate files (default: {TEMP_DIR})"
    )
    parser.add_argument(
        "--output-dir",
        default=FINAL_OUTPUT_DIR,
        help=f"Output directory for final reports and charts (default: {FINAL_OUTPUT_DIR})"
    )
    
    args = parser.parse_args()
    
    # Update global directories if specified
    from config import constants
    constants.TEMP_DIR = args.temp_dir
    constants.FINAL_OUTPUT_DIR = args.output_dir
    constants.OUTPUT_DIR = f"{args.temp_dir}/parsed_statements"
    
    # Validate input directory
    if not Path(args.input_dir).exists():
        print(f"❌ Error: Input directory not found: {args.input_dir}")
        return
    
    if not Path(args.input_dir).is_dir():
        print(f"❌ Error: Input path is not a directory: {args.input_dir}")
        return
    
    # Check for required environment variables
    try:
        validate_api_keys()
    except EnvironmentError as e:
        print(f"❌ Error: {e}")
        return
    
    print("🔍 Configuration validated:")
    print(f"   - Input directory: {args.input_dir}")
    print(f"   - Question: {args.question}")
    print(f"   - Temp directory: {constants.TEMP_DIR}")
    print(f"   - Output directory: {constants.FINAL_OUTPUT_DIR}")
    print(f"   - Anthropic model: {constants.ANTHROPIC_MODEL}")
    print(f"   - OpenAI model: {constants.OPENAI_MODEL}")
    
    # Ensure directories exist
    ensure_directories(constants.TEMP_DIR, constants.FINAL_OUTPUT_DIR, constants.OUTPUT_DIR)
    
    # Run the complete pipeline
    try:
        asyncio.run(run_complete_pipeline(args.input_dir, args.question))
    except KeyboardInterrupt:
        print("\n⚠️ Pipeline interrupted by user")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        print(f"Full traceback: {traceback.format_exc()}")


if __name__ == "__main__":
    main()