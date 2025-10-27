import os
import base64
import json
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import logging
import traceback

logger = logging.getLogger(__name__)

# Google Sheets API scope
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file'
]

# Updated Column mapping for sequential columns (no headers)
# Assuming your columns are in this exact order from left to right
COLUMN_MAPPING = {
    'StudentID': 1,      # Column A - First column
    'StudentName': 2,    # Column B - Second column  
    'ClassRollNo': 3,    # Column C - Third column
    'AdmissionDate': 4,  # Column D
    'Section': 5,        # Column E
    'Group': 6,          # Column F
    'Email': 7,          # Column G
    'Mobile': 8,         # Column H
    'FatherName': 9,     # Column I
    'FoodPreference': 10, # Column J
    'Photo': 11,         # Column K
    'QRCode': 12,        # Column L - QR Code column
    'Status': 13,        # Column M
    'Comment': 14,       # Column N
    'LastCheckedTime': 15, # Column O
    'Coordinator': 16,   # Column P
    'Used': 17           # Column Q
}

def decode_credentials():
    """Decode base64 encoded Google credentials from environment variable"""
    try:
        encoded_creds = os.environ.get('GOOGLE_CREDENTIALS')
        if not encoded_creds:
            raise ValueError("GOOGLE_CREDENTIALS environment variable not set")
        
        logger.info("Starting credential decoding...")
        
        # Decode base64 credentials
        creds_json = base64.b64decode(encoded_creds).decode('utf-8')
        creds_dict = json.loads(creds_json)
        
        logger.info("Credentials decoded successfully")
        logger.info(f"Service account: {creds_dict.get('client_email', 'Unknown')}")
        
        return Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    except Exception as e:
        logger.error(f"❌ Error decoding credentials: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise

def get_sheet():
    """Get Google Sheet worksheet object"""
    try:
        logger.info("Attempting to authenticate with Google Sheets...")
        
        creds = decode_credentials()
        client = gspread.authorize(creds)
        
        logger.info("Successfully authenticated with Google Sheets API")
        
        sheet_id = os.environ.get('GOOGLE_SHEET_ID')
        if not sheet_id:
            raise ValueError("GOOGLE_SHEET_ID environment variable not set")
        
        logger.info(f"Attempting to open sheet with ID: {sheet_id}")
        
        spreadsheet = client.open_by_key(sheet_id)
        worksheet = spreadsheet.sheet1  # Use the first worksheet
        
        logger.info("✅ Successfully connected to Google Sheet")
        logger.info(f"Sheet title: {worksheet.title}")
        
        return worksheet
        
    except gspread.exceptions.APIError as e:
        logger.error(f"❌ Google API Error: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise
    except gspread.exceptions.SpreadsheetNotFound:
        logger.error("❌ Spreadsheet not found. Check GOOGLE_SHEET_ID and sharing permissions.")
        raise
    except Exception as e:
        logger.error(f"❌ Error accessing Google Sheet: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise

def get_cell_value(worksheet, row_index, col_index):
    """Get cell value by row and column index (1-based)"""
    try:
        # Convert to A1 notation
        cell_ref = gspread.utils.rowcol_to_a1(row_index, col_index)
        cell = worksheet.acell(cell_ref)
        return cell.value or ""
    except Exception as e:
        logger.error(f"Error getting cell {cell_ref}: {str(e)}")
        return ""

def fetch_student_by_qrcode(qr_string):
    """Fetch student data by QR code using sequential column positions (no headers)"""
    try:
        worksheet = get_sheet()
        
        # Get all data - no headers, so all rows are data rows
        all_data = worksheet.get_all_values()
        
        logger.info(f"🔍 SEARCHING FOR QR CODE: '{qr_string}'")
        logger.info(f"Total rows in sheet: {len(all_data)}")
        logger.info("📋 No headers detected - treating all rows as data")
        
        # Start from first row (no headers to skip)
        start_row = 1
        
        scanned_code = str(qr_string).strip()
        qr_column = COLUMN_MAPPING['QRCode']  # Column L (12)
        
        logger.info(f"🎯 Searching QR codes in column {qr_column} (L)")
        
        # Search through all rows starting from first row
        for row_index in range(start_row, len(all_data) + 1):
            try:
                # Get QR code value from the specified column
                record_qr = get_cell_value(worksheet, row_index, qr_column)
                record_qr_clean = str(record_qr).strip()
                
                if not record_qr_clean:
                    continue  # Skip empty QR codes
                
                logger.info(f"📝 Row {row_index}: Comparing sheet='{record_qr_clean}' with scanned='{scanned_code}'")
                
                # Multiple matching strategies
                if (record_qr_clean == scanned_code or 
                    record_qr_clean.lower() == scanned_code.lower() or
                    record_qr_clean.replace(' ', '') == scanned_code.replace(' ', '')):
                    
                    # Found match! Get all student data using sequential columns
                    student_data = {}
                    for field, col_index in COLUMN_MAPPING.items():
                        student_data[field] = get_cell_value(worksheet, row_index, col_index)
                    
                    logger.info(f"✅ MATCH FOUND at row {row_index}: {student_data.get('StudentName', 'Unknown')}")
                    logger.info(f"📊 Student Data: {student_data}")
                    return student_data, row_index
                    
            except Exception as e:
                logger.error(f"Error processing row {row_index}: {str(e)}")
                continue
        
        logger.warning(f"❌ QR code '{qr_string}' not found in any of {len(all_data)} data rows")
        
        # Log sample QR codes for debugging
        sample_count = min(5, len(all_data))
        if sample_count > 0:
            logger.info("📊 Sample QR codes from sheet:")
            for i in range(sample_count):
                row_idx = i + 1
                sample_qr = get_cell_value(worksheet, row_idx, qr_column)
                logger.info(f"   Row {row_idx}: '{sample_qr}'")
        
        return None, None
        
    except Exception as e:
        logger.error(f"❌ Error in fetch_student_by_qrcode: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return None, None

def update_student_status_by_row(row_index, status, comment, coordinator):
    """Update student status using sequential column positions"""
    try:
        worksheet = get_sheet()
        
        # Prepare update data
        update_data = {}
        
        # Map fields to column positions
        field_mapping = {
            'Status': status,
            'Comment': comment,
            'Coordinator': coordinator,
            'Used': 'Yes',
            'LastCheckedTime': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        for field, value in field_mapping.items():
            col_index = COLUMN_MAPPING.get(field)
            if col_index:
                update_data[col_index] = value
        
        # Perform batch update
        if update_data:
            cells = []
            for col_index, value in update_data.items():
                cell_ref = gspread.utils.rowcol_to_a1(row_index, col_index)
                cells.append({
                    'range': cell_ref,
                    'values': [[value]]
                })
            
            worksheet.batch_update(cells)
            logger.info(f"✅ Updated row {row_index} with: Status='{status}', Comment='{comment}', Coordinator='{coordinator}'")
            logger.info(f"📝 Update details: {update_data}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error updating student status: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

def debug_sheet_structure():
    """Debug function to check sheet structure and column positions"""
    try:
        worksheet = get_sheet()
        all_data = worksheet.get_all_values()
        
        logger.info("🔍 DEBUG SHEET STRUCTURE (NO HEADERS):")
        logger.info(f"Total rows: {len(all_data)}")
        
        # Show first 3 rows with column indicators
        for i, row in enumerate(all_data[:3]):
            row_display = []
            for j, cell in enumerate(row):
                col_letter = gspread.utils.rowcol_to_a1(1, j+1)[0]  # Get column letter
                row_display.append(f"{col_letter}: '{cell}'")
            logger.info(f"Row {i+1}: {', '.join(row_display)}")
        
        # Check what's in the QR code column
        qr_col = COLUMN_MAPPING['QRCode']
        qr_col_letter = gspread.utils.rowcol_to_a1(1, qr_col)[0]
        logger.info(f"QR Code column: {qr_col_letter} (index {qr_col})")
        
        # Show first 5 QR codes
        sample_qrs = []
        for i in range(min(5, len(all_data))):
            qr_value = get_cell_value(worksheet, i+1, qr_col)
            if qr_value:
                sample_qrs.append(f"Row {i+1}: '{qr_value}'")
        
        if sample_qrs:
            logger.info("Sample QR codes:")
            for qr in sample_qrs:
                logger.info(f"  {qr}")
        else:
            logger.info("No QR codes found in first 5 rows")
        
        # Show column mapping being used
        logger.info("Column mapping being used:")
        for field, col_index in COLUMN_MAPPING.items():
            col_letter = gspread.utils.rowcol_to_a1(1, col_index)[0]
            logger.info(f"  {field}: Column {col_letter} (index {col_index})")
        
        return True
    except Exception as e:
        logger.error(f"Error debugging sheet structure: {str(e)}")
        return False

def test_connection():
    """Test Google Sheets connection"""
    try:
        worksheet = get_sheet()
        all_data = worksheet.get_all_values()
        
        logger.info("✅ Connection test successful!")
        logger.info(f"Sheet title: {worksheet.title}")
        logger.info(f"Total rows: {len(all_data)}")
        logger.info(f"Column mapping: {len(COLUMN_MAPPING)} columns defined")
        
        return True
    except Exception as e:
        logger.error(f"❌ Connection test failed: {str(e)}")
        return False

def get_column_mapping():
    """Get the current column mapping for debugging"""
    return COLUMN_MAPPING

def update_column_mapping(custom_mapping):
    """Update column mapping if your sheet has different column order"""
    global COLUMN_MAPPING
    if isinstance(custom_mapping, dict):
        COLUMN_MAPPING.update(custom_mapping)
        logger.info(f"Updated column mapping: {COLUMN_MAPPING}")
        return True
    return False

# Example of how to customize column mapping if your columns are in different order:
# If your columns are in a different order, you can update the mapping like this:
#
# CUSTOM_MAPPING = {
#     'StudentID': 1,      # Your Student ID column
#     'StudentName': 2,    # Your Student Name column  
#     'QRCode': 3,         # Your QR Code column (if it's in column C)
#     # ... etc
# }
# update_column_mapping(CUSTOM_MAPPING)