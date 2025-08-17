import pypdf
import os
from typing import List

def convert_pdfs_in_dir(input_dir: str, output_dir: str = "temp") -> List[str]:
    """
    Scans a directory for PDF files, extracts text, and saves each to a text file.

    This function searches the specified input directory for any files with a '.pdf'
    extension. It then extracts the text from each PDF and saves it to a new file 
    in the output directory. The output files are named sequentially 
    (e.g., statement1.txt, statement2.txt).

    Args:
        input_dir (str): The path to the directory containing the PDF files.
        output_dir (str): The name of the directory to save the text files.
                          Defaults to 'temp'.

    Returns:
        List[str]: A list of paths to the newly created text files.
                   Returns an empty list if the input directory doesn't exist
                   or contains no PDF files.
    """
    # Check if the input directory exists
    if not os.path.isdir(input_dir):
        print(f"Error: Input directory '{input_dir}' not found.")
        return []

    # Find all files in the directory that end with .pdf (case-insensitive)
    pdf_files = [
        os.path.join(input_dir, filename)
        for filename in os.listdir(input_dir)
        if filename.lower().endswith(".pdf") and os.path.isfile(os.path.join(input_dir, filename))
    ]

    if not pdf_files:
        print(f"No PDF files found in '{input_dir}'.")
        return []

    # Create the output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    created_text_files = []

    # Enumerate through the list of discovered PDFs to process them
    for i, file_path in enumerate(pdf_files, start=1):
        try:
            print(f"Processing '{file_path}'...")
            reader = pypdf.PdfReader(file_path)
            full_text = ""
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    full_text += page_text + "\n"
            
            # Define the output file name and path
            output_filename = f"statement{i}.txt"
            output_path = os.path.join(output_dir, output_filename)
            
            # Write the extracted text to the new file
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(full_text)
            
            created_text_files.append(output_path)
            print(f"Successfully created '{output_path}'")

        except Exception as e:
            print(f"Error processing file {file_path}: {str(e)}")
            
    return created_text_files

# --- Example Usage ---
if __name__ == '__main__':
    # Create a sample directory for our PDF files
    source_directory = "temp"
    
    # Call the function to convert all PDFs in the directory
    saved_files = convert_pdfs_in_dir(source_directory)
    
    print("\n--- Conversion Complete ---")
    if saved_files:
        print("The following text files were created in the 'temp' directory:")
        for file in saved_files:
            print(f"- {file}")
    else:
        print("No files were created.")