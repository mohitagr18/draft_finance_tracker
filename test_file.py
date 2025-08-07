#!/usr/bin/env python3
"""
AutoGen PDF Processing System - Version 0.7.2 Compatible

A multi-agent system that processes PDF files and extracts structured data
using Microsoft AutoGen framework version 0.7.2 with RoundRobinGroupChat.

Usage:
    python pdf_processor.py <pdf_path> [options]
    
Options:
    --output-dir <dir>    Directory to save output files (default: current directory)
    --output-format <fmt> Output format: 'print', 'json', 'csv', 'both' (default: 'print')
    --api-key <key>       OpenAI API key (or set OPENAI_API_KEY environment variable)
    --model <model>       Model to use (default: gpt-4o-mini)

Examples:
    python pdf_processor.py document.pdf --output-format print
    python pdf_processor.py document.pdf --output-format both --output-dir ./results
"""

import json
import pandas as pd
import pypdf
import argparse
import os
import sys
import tempfile
import asyncio
from typing import Dict, Any, List, Optional, Sequence
from autogen_agentchat.agents import AssistantAgent, CodeExecutorAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.messages import TextMessage
from autogen_core._cancellation_token import CancellationToken
from autogen_ext.code_executors.local import LocalCommandLineCodeExecutor
from dotenv import load_dotenv

load_dotenv()


def extract_text_from_pdf(file_path: str) -> str:
    """
    Extracts all text content from a given PDF file.

    This tool's purpose is to provide the raw text data from a PDF to an LLM agent.
    The agent will then be responsible for writing code to parse this unstructured text.

    Args:
        file_path (str): The local path to the PDF file.

    Returns:
        str: A single string containing all the extracted text from the PDF.
             Returns an error message string if extraction fails.
    """
    try:
        reader = pypdf.PdfReader(file_path)
        full_text = ""
        for page in reader.pages:
            full_text += page.extract_text() + "\n--- End of Page ---\n"
        return full_text
    except Exception as e:
        return f"Error extracting text from PDF: {str(e)}"


def create_agents(model_config: Dict[str, Any], work_dir: str) -> List:
    """
    Create all the agents needed for PDF processing.
    
    Args:
        model_config: Configuration for the language model
        work_dir: Working directory for code execution
        
    Returns:
        List of agents in processing order
    """
    agents = []
    
    # 1. Data Extraction Agent - Analyzes PDF text structure
    extractor = AssistantAgent(
        name="DataExtractor",
        model_client=model_config,
        system_message="""You are a data extraction expert. Your job is to:

1. Analyze the raw PDF text provided to you
2. Identify the structure and patterns in the data (tables, forms, lists, etc.)
3. Determine what type of structured data this represents
4. Identify key fields, columns, or data points that should be extracted
5. Provide a detailed analysis of the data structure to guide the parsing process

Be thorough in your analysis and clearly describe:
- Data organization patterns (rows, columns, sections)
- Headers and separators used
- Repeating structures or records
- Key data fields and their types
- Suggested extraction approach

Focus on understanding the complete data structure, not just samples.
Provide your analysis in a clear, structured format that the next agent can use.""",
    )
    
    # 2. Code Generator Agent - Creates parsing code
    coder = AssistantAgent(
        name="CodeGenerator",
        model_client=model_config,
        system_message="""You are a Python coding expert specializing in data parsing. Your job is to:

1. Take the data structure analysis from the DataExtractor
2. Write comprehensive Python code to parse the raw PDF text into structured data
3. Create robust functions that handle edge cases and data cleaning
4. Generate code that processes ALL available data, not just samples
5. Ensure output in both JSON and CSV formats

Your code should:
- Import necessary libraries (pandas, json, re, etc.)
- Include comprehensive error handling with try-except blocks
- Be well-commented and readable
- Save results to files: 'extracted_data.json' and 'extracted_data.csv'
- Use descriptive variable names
- Handle variations in text format gracefully
- Process the complete dataset systematically

IMPORTANT: Provide complete, executable Python code wrapped in ```python``` blocks.
The code should be self-contained and ready to run with the PDF text as input.
Always save the final structured data to both JSON and CSV files.""",
    )
    
    # 3. Code Executor Agent - Runs and tests the code
    code_executor = CodeExecutorAgent(
        name="CodeExecutor",
        model_client=model_config,
        code_executor=LocalCommandLineCodeExecutor(work_dir=work_dir),
        system_message="""You are responsible for executing and testing the parsing code. Your job is to:

1. Execute the Python code generated by the CodeGenerator
2. Run the code with the actual PDF text data
3. Verify that all data is properly extracted and structured
4. Report execution results, including any errors
5. Confirm that output files are created successfully
6. Show sample of the structured data output

When executing code:
- Run all provided code blocks completely
- Report any errors with specific details
- Confirm successful file creation with file sizes
- Display sample output to verify data quality
- If there are issues, suggest specific improvements

Be thorough in testing and provide clear feedback on the results.""",
    )
    
    # 4. Quality Assurance Agent - Reviews output
    qa_agent = AssistantAgent(
        name="QualityAssurance",
        model_client=model_config,
        system_message="""You are a quality assurance specialist. Your job is to:

1. Review the structured data output from the parsing process
2. Verify data completeness - ensure all information from PDF is captured
3. Check data consistency and format correctness
4. Validate JSON structure is logical and well-organized
5. Ensure tabular format is properly structured
6. Provide final approval or request specific corrections

Be thorough in your review:
- Check for missing or incomplete data extraction
- Verify data types are appropriate and consistent
- Ensure proper formatting and structure
- Validate logical relationships in the data
- Confirm output files were created successfully
- Review sample data for accuracy

If you find issues, be specific about what needs to be corrected.
Provide final approval when the output meets quality standards.""",
    )
    
    agents = [extractor, coder, code_executor, qa_agent]
    return agents


def get_model_client(api_key: str = None, model: str = "gpt-4o"):
    """
    Get model client configuration for AutoGen 0.7.2.
    
    Args:
        api_key: OpenAI API key
        model: Model name to use
        
    Returns:
        Model client instance
    """
    if not api_key:
        api_key = os.getenv("OPENAI_API_KEY2")
    
    if not api_key:
        raise ValueError("OpenAI API key not provided. Set OPENAI_API_KEY environment variable or use --api-key")
    
    # Import the correct model client for AutoGen 0.7.2
    try:
        from autogen_ext.models import OpenAIChatCompletionClient
        
        return OpenAIChatCompletionClient(
            model=model,
            api_key=api_key,
            temperature=0.1,
        )
    except ImportError:
        # Fallback if the above doesn't work
        from autogen_core.components.models import OpenAIChatCompletionClient
        
        return OpenAIChatCompletionClient(
            model=model,
            api_key=api_key,
            temperature=0.1,
        )


async def process_pdf_with_team(pdf_text: str, agents: List, work_dir: str) -> Dict[str, Any]:
    """
    Process the PDF text using the RoundRobinGroupChat team.
    
    Args:
        pdf_text: Extracted text from PDF
        agents: List of agents
        work_dir: Working directory for file operations
        
    Returns:
        Processing results
    """
    # Create the RoundRobinGroupChat team
    team = RoundRobinGroupChat(participants=agents)
    
    # Prepare the initial message
    initial_message = TextMessage(
        content=f"""
TASK: Process PDF text and convert to structured data

We need to systematically process the following PDF text and convert it into structured data files.

PDF TEXT TO PROCESS:
---PDF TEXT START---
{pdf_text}
---PDF TEXT END---

WORKFLOW STEPS:
1. DataExtractor: Analyze the text structure and identify data patterns
2. CodeGenerator: Write comprehensive Python code to parse this text
3. CodeExecutor: Execute the code and generate structured data files  
4. QualityAssurance: Review output for completeness and accuracy

REQUIREMENTS:
- Process ALL data from the PDF, not just samples
- Generate both 'extracted_data.json' and 'extracted_data.csv' files
- Ensure data is well-structured and complete
- Working directory: {work_dir}

Let's begin the structured data extraction process!
""",
        source="user"
    )
    
    try:
        print("🤖 Starting RoundRobinGroupChat team processing...")
        print("📋 Team workflow: DataExtractor → CodeGenerator → CodeExecutor → QualityAssurance")
        
        # Run the team with the initial message
        result = await team.run(task=initial_message, cancellation_token=CancellationToken())
        
        return {
            "success": True,
            "result": result,
            "work_dir": work_dir
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "work_dir": work_dir
        }


def find_generated_files(work_dir: str) -> List[str]:
    """
    Find all generated data files in the work directory.
    
    Args:
        work_dir: Directory to search
        
    Returns:
        List of generated file paths
    """
    generated_files = []
    
    if not os.path.exists(work_dir):
        return generated_files
    
    for file in os.listdir(work_dir):
        if file.endswith(('.json', '.csv', '.xlsx', '.txt')) and not file.startswith('.'):
            full_path = os.path.join(work_dir, file)
            if os.path.getsize(full_path) > 0:  # Only include non-empty files
                generated_files.append(full_path)
    
    return generated_files


def print_results(generated_files: List[str]) -> None:
    """
    Print the contents of generated files.
    
    Args:
        generated_files: List of file paths to print
    """
    for file_path in generated_files:
        print(f"\n{'='*60}")
        print(f"📄 FILE: {os.path.basename(file_path)}")
        print(f"📁 PATH: {file_path}")
        print(f"💾 SIZE: {os.path.getsize(file_path)} bytes")
        print(f"{'='*60}")
        
        try:
            if file_path.endswith('.json'):
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                print("📊 JSON DATA:")
                json_str = json.dumps(data, indent=2, ensure_ascii=False)
                if len(json_str) > 3000:
                    print(json_str[:3000] + "\n... (truncated for display)")
                else:
                    print(json_str)
                    
            elif file_path.endswith('.csv'):
                df = pd.read_csv(file_path)
                print("📊 CSV DATA:")
                print(f"Shape: {df.shape} (rows x columns)")
                print("\nFirst 10 rows:")
                print(df.head(10).to_string(index=False))
                if len(df) > 10:
                    print(f"\n... and {len(df) - 10} more rows")
                    
            else:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                print("📄 FILE CONTENT:")
                if len(content) > 3000:
                    print(content[:3000] + "\n... (truncated for display)")
                else:
                    print(content)
                    
        except Exception as e:
            print(f"❌ Error reading file {file_path}: {e}")


def copy_files_to_output(generated_files: List[str], output_dir: str, base_name: str) -> List[str]:
    """
    Copy generated files to the output directory with proper naming.
    
    Args:
        generated_files: List of generated file paths
        output_dir: Output directory
        base_name: Base name for output files
        
    Returns:
        List of final file paths
    """
    final_files = []
    
    for i, file_path in enumerate(generated_files):
        ext = os.path.splitext(file_path)[1]
        original_name = os.path.splitext(os.path.basename(file_path))[0]
        
        # Create descriptive filename
        if 'extracted_data' in original_name or 'data' in original_name:
            new_name = f"{base_name}_processed{ext}"
        else:
            new_name = f"{base_name}_{original_name}{ext}"
        
        # Handle duplicates
        counter = 1
        final_path = os.path.join(output_dir, new_name)
        while os.path.exists(final_path):
            name_part = os.path.splitext(new_name)[0]
            ext_part = os.path.splitext(new_name)[1]
            final_path = os.path.join(output_dir, f"{name_part}_{counter}{ext_part}")
            counter += 1
        
        try:
            import shutil
            shutil.copy2(file_path, final_path)
            final_files.append(final_path)
            print(f"✅ Saved: {final_path}")
        except Exception as e:
            print(f"❌ Error copying {file_path}: {e}")
    
    return final_files


def main():
    """Main function to run the PDF processor."""
    parser = argparse.ArgumentParser(
        description="Process PDF files using AutoGen 0.7.2 RoundRobinGroupChat team",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument("pdf_path", help="Path to the PDF file to process")
    parser.add_argument("--output-dir", default=".", help="Directory to save output files")
    parser.add_argument("--output-format", choices=['print', 'json', 'csv', 'both'], 
                       default='print', help="Output format")
    parser.add_argument("--api-key", help="OpenAI API key")
    parser.add_argument("--model", default="gpt-4o-mini", help="Model to use")
    
    args = parser.parse_args()
    
    # Validate inputs
    if not os.path.exists(args.pdf_path):
        print(f"❌ Error: PDF file not found: {args.pdf_path}")
        sys.exit(1)
    
    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)
    
    # Create temporary working directory
    work_dir = tempfile.mkdtemp(prefix="pdf_processor_")
    
    try:
        print(f"📖 Processing PDF: {args.pdf_path}")
        print(f"💾 Output directory: {args.output_dir}")
        print(f"🔧 Working directory: {work_dir}")
        
        # Extract text from PDF
        print("📄 Extracting text from PDF...")
        pdf_text = extract_text_from_pdf(args.pdf_path)
        if pdf_text.startswith("Error"):
            print(f"❌ {pdf_text}")
            sys.exit(1)
        
        print(f"✅ Extracted {len(pdf_text)} characters from PDF")
        
        # Get model client
        try:
            model_client = get_model_client(args.api_key, args.model)
            print(f"🧠 Using model: {args.model}")
        except ValueError as e:
            print(f"❌ {e}")
            sys.exit(1)
        except ImportError as e:
            print(f"❌ Import error: {e}")
            print("💡 Make sure you have the correct AutoGen 0.7.2 packages installed:")
            print("   pip install autogen-agentchat autogen-ext autogen-core")
            sys.exit(1)
        
        # Create agents
        print("🤖 Creating AI agents...")
        agents = create_agents(model_client, work_dir)
        
        print("🚀 Starting RoundRobinGroupChat team processing...")
        
        # Process the PDF text using async
        result = asyncio.run(process_pdf_with_team(pdf_text, agents, work_dir))
        
        if not result["success"]:
            print(f"❌ Processing failed: {result.get('error', 'Unknown error')}")
            sys.exit(1)
        
        print("✅ Team processing completed!")
        
        # Find generated files
        generated_files = find_generated_files(work_dir)
        
        if not generated_files:
            print("⚠️  No output files were generated by the team")
            print("💡 This might happen if:")
            print("   - The PDF content was too complex to parse")
            print("   - The parsing code had errors")
            print("   - The file writing failed")
            print(f"\n📁 Check working directory: {work_dir}")
            sys.exit(1)
        
        print(f"📁 Found {len(generated_files)} generated files:")
        for f in generated_files:
            print(f"   - {os.path.basename(f)} ({os.path.getsize(f)} bytes)")
        
        # Handle output based on format
        base_name = os.path.splitext(os.path.basename(args.pdf_path))[0]
        
        if args.output_format == 'print':
            print_results(generated_files)
        else:
            # Copy files to output directory
            print(f"\n📋 Copying files to output directory...")
            final_files = copy_files_to_output(generated_files, args.output_dir, base_name)
            
            if not final_files:
                print("❌ No files were successfully copied to output directory")
                print_results(generated_files)
        
        print(f"\n🎉 Processing complete!")
        print(f"📊 Generated {len(generated_files)} structured data files")
        print(f"💾 Files available in: {args.output_dir}")
        
    except KeyboardInterrupt:
        print("\n⚠️  Processing interrupted by user")
        sys.exit(1)
        
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
        
    finally:
        # Cleanup temporary directory
        try:
            import shutil
            shutil.rmtree(work_dir)
            print(f"🧹 Cleaned up temporary directory")
        except Exception as e:
            print(f"⚠️  Warning: Could not clean up temp directory: {e}")


if __name__ == "__main__":
    main()