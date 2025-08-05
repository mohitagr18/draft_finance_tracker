import pypdf

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
