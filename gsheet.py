import os
import base64
import json
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Google Sheets API scope
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file'
]

# Expected column headers (exact matches)
EXPECTED_COLUMNS = [
    'StudentID', 'StudentName', 'ClassRollNo', 'AdmissionDate', 'Section', 
    'Group', 'Email', 'Mobile', 'FatherName', 'FoodPreference', 'Photo', 
    'QRCode', 'Status', 'Comment', 'LastCheckedTime', 'Coordinator', 'Used'
]

# Common variants for column headers (for graceful handling)
COLUMN_VARIANTS = {
    'StudentID': ['Student ID', 'StudentID', 'ID'],
    'StudentName': ['Student Name', 'StudentName', 'Name'],
    'QRCode': ['QR Code', 'QRCode', 'QR', 'QR String', 'QRValue', 'M'],
    'Used': ['Used', 'Scanned', 'Checked'],
    'Coordinator': ['Coordinator', 'Checked By', 'Verified By'],
    'LastCheckedTime': ['Last Checked Time', 'Timestamp', 'Checked Time']
}

def decode_credentials():
    """Decode base64 encoded Google credentials from environment variable"""
    try:
        encoded_creds = os.environ.get('GOOGLE_CREDENTIALS')
        if not encoded_creds:
            raise ValueError("GOOGLE_CREDENTIALS environment variable not set")
        
        # Decode base64 credentials
        creds_json = base64.b64decode(encoded_creds).decode('utf-8')
        creds_dict = json.loads(creds_json)
        
        return Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    except Exception as e:
        logger.error(f"Error decoding credentials: {str(e)}")
        raise

def get_sheet():
    """Get Google Sheet worksheet object"""
    try:
        creds = decode_credentials()
        client = gspread.authorize(creds)
        
        sheet_id = os.environ.get('GOOGLE_SHEET_ID')
        if not sheet_id:
            raise ValueError("GOOGLE_SHEET_ID environment variable not set")
        
        spreadsheet = client.open_by_key(sheet_id)
        worksheet = spreadsheet.sheet1  # Use the first worksheet
        
        logger.info("Successfully connected to Google Sheet")
        return worksheet
        
    except gspread.exceptions.APIError as e:
        logger.error(f"Google API Error: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error accessing Google Sheet: {str(e)}")
        raise

def ensure_columns(worksheet):
    """Ensure all expected columns exist in the sheet"""
    try:
        # Get current headers
        current_headers = worksheet.row_values(1)
        
        # If sheet is empty, add all expected columns
        if not current_headers:
            logger.info("Sheet is empty, adding all expected columns")
            worksheet.update('A1', [EXPECTED_COLUMNS])
            return
        
        missing_columns = []
        for expected_col in EXPECTED_COLUMNS:
            if expected_col not in current_headers:
                # Check for variants
                found_variant = False
                for variant in COLUMN_VARIANTS.get(expected_col, []):
                    if variant in current_headers:
                        found_variant = True
                        break
                
                if not found_variant:
                    missing_columns.append(expected_col)
        
        # Add missing columns
        if missing_columns:
            logger.info(f"Adding missing columns: {missing_columns}")
            updated_headers = current_headers + missing_columns
            worksheet.update('A1', [updated_headers])
            logger.info("Successfully updated sheet headers")
        else:
            logger.info("All expected columns are present")
            
    except Exception as e:
        logger.error(f"Error ensuring columns: {str(e)}")
        raise

def fetch_student_by_qrcode(qr_string):
    """Fetch student data by QR code string - matches raw code values in QRCode column"""
    try:
        worksheet = get_sheet()
        
        # Get all records
        records = worksheet.get_all_records()
        
        logger.info(f"🔍 SEARCHING FOR QR CODE: '{qr_string}'")
        logger.info(f"Total records in sheet: {len(records)}")
        
        # Get the header row to find the exact QR code column name
        headers = worksheet.row_values(1)
        logger.info(f"📋 Sheet headers: {headers}")
        
        # Find the actual QR code column name being used
        qr_column_name = None
        for header in headers:
            if any(variant.lower() in header.lower() for variant in COLUMN_VARIANTS['QRCode']):
                qr_column_name = header
                break
        
        if qr_column_name:
            logger.info(f"🎯 Using QR code column: '{qr_column_name}'")
        else:
            logger.warning("❌ No QR code column found in sheet headers")
            # Try using column M directly
            if len(headers) >= 13:  # M is the 13th column (0-indexed 12)
                qr_column_name = headers[12]  # Column M
                logger.info(f"🔤 Using column M directly: '{qr_column_name}'")
        
        # Find student by QR code (flexible matching)
        found_match = False
        for index, record in enumerate(records, start=2):  # start=2 because row 1 is headers
            
            # Get QR code value using the identified column name
            record_qr = ""
            if qr_column_name and qr_column_name in record:
                record_qr = record[qr_column_name] or ""
            else:
                # Fallback: try all possible column names
                for col_name in COLUMN_VARIANTS['QRCode']:
                    if col_name in record and record[col_name]:
                        record_qr = record[col_name]
                        break
            
            if not record_qr:
                continue  # Skip if no QR code value
            
            # Clean both strings for comparison
            sheet_code = str(record_qr).strip()
            scanned_code = str(qr_string).strip()
            
            logger.info(f"📝 Row {index}: Comparing sheet='{sheet_code}' with scanned='{scanned_code}'")
            
            # Multiple matching strategies
            
            # 1. Exact match (case-sensitive)
            if sheet_code == scanned_code:
                logger.info(f"✅ EXACT MATCH at row {index}: {record.get('StudentName', 'Unknown')}")
                found_match = True
                return record, index
            
            # 2. Case-insensitive match
            if sheet_code.lower() == scanned_code.lower():
                logger.info(f"✅ CASE-INSENSITIVE MATCH at row {index}: {record.get('StudentName', 'Unknown')}")
                found_match = True
                return record, index
            
            # 3. Match after removing all whitespace
            if sheet_code.replace(' ', '').replace('\t', '').replace('\n', '') == scanned_code.replace(' ', '').replace('\t', '').replace('\n', ''):
                logger.info(f"✅ WHITESPACE-INSENSITIVE MATCH at row {index}: {record.get('StudentName', 'Unknown')}")
                found_match = True
                return record, index
            
            # 4. Partial match (if one contains the other)
            if scanned_code in sheet_code or sheet_code in scanned_code:
                logger.info(f"⚠️  PARTIAL MATCH at row {index}: sheet='{sheet_code}' scanned='{scanned_code}'")
                # Don't return for partial matches, but log for debugging
        
        if not found_match:
            logger.warning(f"❌ QR code '{qr_string}' not found in database after checking {len(records)} records")
            
            # Log first few QR values for debugging
            sample_qr_codes = []
            for i, record in enumerate(records[:10]):  # First 10 records
                record_qr = ""
                if qr_column_name and qr_column_name in record:
                    record_qr = record[qr_column_name] or ""
                else:
                    for col_name in COLUMN_VARIANTS['QRCode']:
                        if col_name in record and record[col_name]:
                            record_qr = record[col_name]
                            break
                
                if record_qr:
                    sample_qr_codes.append(f"Row {i+2}: '{record_qr.strip()}'")
            
            if sample_qr_codes:
                logger.info(f"📊 Sample QR codes in sheet:")
                for code in sample_qr_codes:
                    logger.info(f"   {code}")
            else:
                logger.info("📭 No QR codes found in the first 10 records")
            
            # Also check if we can find any record at all
            if records:
                first_record_keys = list(records[0].keys())
                logger.info(f"🔑 First record keys: {first_record_keys}")
                if qr_column_name and qr_column_name in records[0]:
                    logger.info(f"📦 First record QR value: '{records[0][qr_column_name]}'")
        
        return None, None
        
    except Exception as e:
        logger.error(f"❌ Error fetching student by QR code: {str(e)}")
        return None, None

def update_student_status_by_row(row_index, status, comment, coordinator):
    """Update student status and mark as used"""
    try:
        worksheet = get_sheet()
        
        # Get current headers to find column indices
        headers = worksheet.row_values(1)
        
        # Map column names to indices
        col_map = {header: index + 1 for index, header in enumerate(headers)}  # 1-based for gspread
        
        # Prepare update data
        update_data = {}
        
        # Map our internal column names to actual sheet headers
        status_col = None
        for col_name in ['Status', 'status']:
            if col_name in col_map:
                status_col = col_map[col_name]
                break
        if not status_col:
            # Find by case-insensitive match
            for idx, header in enumerate(headers):
                if header.lower() == 'status':
                    status_col = idx + 1
                    break
        
        if status_col:
            update_data[status_col] = status
        
        # Similarly for other columns...
        comment_col = None
        for col_name in ['Comment', 'comment']:
            if col_name in col_map:
                comment_col = col_map[col_name]
                break
        if not comment_col:
            for idx, header in enumerate(headers):
                if header.lower() == 'comment':
                    comment_col = idx + 1
                    break
        if comment_col:
            update_data[comment_col] = comment
        
        coordinator_col = None
        for col_name in ['Coordinator', 'coordinator']:
            if col_name in col_map:
                coordinator_col = col_map[col_name]
                break
        if not coordinator_col:
            for idx, header in enumerate(headers):
                if header.lower() == 'coordinator':
                    coordinator_col = idx + 1
                    break
        if coordinator_col:
            update_data[coordinator_col] = coordinator
        
        used_col = None
        for col_name in ['Used', 'used']:
            if col_name in col_map:
                used_col = col_map[col_name]
                break
        if not used_col:
            for idx, header in enumerate(headers):
                if header.lower() == 'used':
                    used_col = idx + 1
                    break
        if used_col:
            update_data[used_col] = 'Yes'
        
        # Always update timestamp
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        time_col = None
        for col_name in ['LastCheckedTime', 'lastcheckedtime', 'Timestamp', 'timestamp']:
            if col_name in col_map:
                time_col = col_map[col_name]
                break
        if not time_col:
            for idx, header in enumerate(headers):
                if header.lower() in ['lastcheckedtime', 'timestamp']:
                    time_col = idx + 1
                    break
        if time_col:
            update_data[time_col] = current_time
        
        # Perform batch update
        if update_data:
            cells = []
            for col, value in update_data.items():
                cells.append({
                    'range': f"{gspread.utils.rowcol_to_a1(row_index, col)}",
                    'values': [[value]]
                })
            
            worksheet.batch_update(cells)
            logger.info(f"✅ Updated row {row_index} with {len(update_data)} fields")
            logger.info(f"📝 Update details: Status='{status}', Comment='{comment}', Coordinator='{coordinator}'")
        
        # Simple backup reminder
        backup_check()
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error updating student status: {str(e)}")
        return False

def get_all_records():
    """Get all student records from the sheet"""
    try:
        worksheet = get_sheet()
        return worksheet.get_all_records()
    except Exception as e:
        logger.error(f"Error fetching all records: {str(e)}")
        return []

def backup_check():
    """Simple backup mechanism - logs backup reminder"""
    logger.info("💾 Backup check - consider implementing actual backup logic")

# Additional debug function
def debug_sheet_structure():
    """Debug function to check sheet structure"""
    try:
        worksheet = get_sheet()
        headers = worksheet.row_values(1)
        records = worksheet.get_all_records()
        
        logger.info("🔍 DEBUG SHEET STRUCTURE:")
        logger.info(f"Headers: {headers}")
        logger.info(f"Total records: {len(records)}")
        
        # Check QR code column specifically
        qr_columns = []
        for header in headers:
            if any(variant.lower() in header.lower() for variant in COLUMN_VARIANTS['QRCode']):
                qr_columns.append(header)
        
        logger.info(f"QR Code columns found: {qr_columns}")
        
        # Show first 5 QR values
        if records:
            logger.info("First 5 QR values:")
            for i in range(min(5, len(records))):
                qr_value = ""
                for col in qr_columns:
                    if col in records[i] and records[i][col]:
                        qr_value = records[i][col]
                        break
                logger.info(f"  Row {i+2}: '{qr_value}'")
        
        return True
    except Exception as e:
        logger.error(f"Error debugging sheet structure: {str(e)}")
        return False