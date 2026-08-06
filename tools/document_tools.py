import os
import pypdf
import pandas as pd
import logging

logger = logging.getLogger(__name__)

def extract_text_from_pdf(file_path: str, max_pages: int = 50) -> str:
    """
    Extract text from a PDF file.
    """
    try:
        reader = pypdf.PdfReader(file_path)
        num_pages = len(reader.pages)
        pages_to_read = min(num_pages, max_pages)
        
        text = f"--- PDF Document: {os.path.basename(file_path)} ({num_pages} pages) ---\n"
        for i in range(pages_to_read):
            page_text = reader.pages[i].extract_text()
            if page_text:
                text += f"\n--- Page {i+1} ---\n{page_text}"
        
        if num_pages > max_pages:
            text += f"\n\n[Truncated: Only first {max_pages} pages were read to prevent context overflow.]"
            
        return text
    except Exception as e:
        logger.error(f"Error extracting PDF: {e}")
        return f"Error reading PDF file: {str(e)}"

def extract_data_from_excel(file_path: str) -> str:
    """
    Extract data from CSV or Excel file and return a structured text summary.
    """
    try:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.csv':
            df = pd.read_csv(file_path)
        else:
            df = pd.read_excel(file_path)
            
        # Get sheet info and summary stats
        num_rows, num_cols = df.shape
        summary = (
            f"--- Spreadsheet: {os.path.basename(file_path)} ---\n"
            f"Dimensions: {num_rows} rows, {num_cols} columns\n"
            f"Columns: {', '.join(df.columns.tolist())}\n\n"
            f"**Preview (First 15 Rows):**\n"
            f"{df.head(15).to_markdown(index=False)}\n"
        )
        return summary
    except Exception as e:
        logger.error(f"Error reading Excel/CSV: {e}")
        return f"Error reading spreadsheet file: {str(e)}"

def read_text_file(file_path: str) -> str:
    """
    Read content of a plain text file.
    """
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read(50000) # Limit to first 50k chars
            if len(content) >= 50000:
                content += "\n\n[Truncated: File is larger than 50,000 characters]"
            return f"--- Text Document: {os.path.basename(file_path)} ---\n\n{content}"
    except Exception as e:
        return f"Error reading text file: {str(e)}"

def process_uploaded_document(file_path: str) -> str:
    """
    Detect file type and extract content.
    """
    if not os.path.exists(file_path):
        return f"Error: File not found at path {file_path}"
        
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext == '.pdf':
        return extract_text_from_pdf(file_path)
    elif ext in ['.xlsx', '.xls', '.csv']:
        return extract_data_from_excel(file_path)
    elif ext in ['.txt', '.json', '.md', '.log']:
        return read_text_file(file_path)
    else:
        return f"Unsupported file format '{ext}'. Supported formats: PDF, CSV, Excel, TXT, JSON, MD."
