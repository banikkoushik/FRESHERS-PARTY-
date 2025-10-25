import os
import base64
import json
import logging
from dotenv import load_dotenv
import os
load_dotenv()
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for

# Import the gsheet helper
from gsheet import get_sheet, ensure_columns, fetch_student_by_qrcode, update_student_status_by_row

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'fresh-checks-secret-key-2024')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Hardcoded coordinator credentials (you can change these later)
COORDINATORS = {
    "Soumya": "PCE001",
    "Ankit": "PCE002", 
    "Riya": "PCE003",
    "Devraj": "PCE004"
}

@app.route('/')
def index():
    """Redirect to login page"""
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Coordinator login page"""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        coordinator_id = request.form.get('coordinator_id', '').strip()
        
        # Validate coordinator credentials
        if name in COORDINATORS and COORDINATORS[name] == coordinator_id:
            session['coordinator_name'] = name
            session['coordinator_id'] = coordinator_id
            session['authenticated'] = True
            logger.info(f"Coordinator {name} logged in successfully")
            return redirect(url_for('scan'))
        else:
            return render_template('login.html', error="Invalid Name or ID")
    
    return render_template('login.html')

@app.route('/scan')
def scan():
    """QR scanning page"""
    # Check if coordinator is authenticated
    if not session.get('authenticated'):
        return redirect(url_for('login'))
    
    return render_template('scan.html', 
                         coordinator_name=session.get('coordinator_name'))

@app.route('/result', methods=['GET', 'POST'])
def result():
    """Display student result page"""
    if request.method == 'POST':
        # Get data from form submission
        student_data_json = request.form.get('student_data', '{}')
        row_index = request.form.get('row_index', '')
        
        try:
            student_data = json.loads(student_data_json)
            return render_template('result.html', 
                                student_data=student_data,
                                row_index=row_index,
                                coordinator_name=session.get('coordinator_name'))
        except json.JSONDecodeError:
            return redirect(url_for('scan'))
    
    # If GET request, redirect to scan
    return redirect(url_for('scan'))

@app.route('/fetch', methods=['POST'])
def fetch_student():
    """Fetch student data by QR code"""
    try:
        # Validate coordinator authentication
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401
        
        data = request.get_json()
        qr_string = data.get('qr_string', '').strip()
        
        if not qr_string:
            return jsonify({'error': 'QR string is required'}), 400
        
        logger.info(f"Fetching student with QR: {qr_string}")
        
        # Fetch student data from Google Sheet
        student_data, row_index = fetch_student_by_qrcode(qr_string)
        
        if not student_data:
            return jsonify({'error': 'QR code not found in database'}), 404
        
        # Check if QR has already been used
        if student_data.get('Used', '').lower() == 'yes':
            return jsonify({
                'error': 'QR already used',
                'used_by': student_data.get('Coordinator', 'Unknown'),
                'used_at': student_data.get('LastCheckedTime', 'Unknown time')
            }), 409
        
        # Return only necessary student data for display
        response_data = {
            'row_index': row_index,
            'student_data': {
                'StudentID': student_data.get('StudentID', ''),
                'StudentName': student_data.get('StudentName', ''),
                'ClassRollNo': student_data.get('ClassRollNo', ''),
                'Section': student_data.get('Section', ''),
                'Group': student_data.get('Group', ''),
                'Email': student_data.get('Email', ''),
                'Mobile': student_data.get('Mobile', ''),
                'FoodPreference': student_data.get('FoodPreference', ''),
                'Photo': student_data.get('Photo', ''),
                'Status': student_data.get('Status', ''),
                'Comment': student_data.get('Comment', '')
            }
        }
        
        logger.info(f"Found student: {student_data.get('StudentName')}")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error fetching student: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/update', methods=['POST'])
def update_student():
    """Update student status after verification"""
    try:
        # Validate coordinator authentication
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401
        
        data = request.get_json()
        row_index = data.get('row_index')
        status = data.get('status', '')
        comment = data.get('comment', '')
        
        if not row_index:
            return jsonify({'error': 'Row index is required'}), 400
        
        coordinator_name = session.get('coordinator_name')
        
        logger.info(f"Updating row {row_index} with status: {status}")
        
        # Update student record in Google Sheet
        success = update_student_status_by_row(
            row_index=row_index,
            status=status,
            comment=comment,
            coordinator=coordinator_name
        )
        
        if success:
            # Clear session to force re-authentication for next scan
            session.clear()
            logger.info(f"Successfully updated row {row_index}")
            return jsonify({'success': True, 'message': 'Status updated successfully'})
        else:
            return jsonify({'error': 'Failed to update record'}), 500
            
    except Exception as e:
        logger.error(f"Error updating student: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/health')
def health_check():
    """Health check endpoint for Render"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'FRESH CHECKS QR Gate'
    })

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    # Initialize Google Sheets connection and ensure columns
    try:
        sheet = get_sheet()
        ensure_columns(sheet)
        logger.info("Google Sheets connection established successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Google Sheets: {str(e)}")
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)