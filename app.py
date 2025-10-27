import os
import base64
import json
import logging
from dotenv import load_dotenv
import secrets
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for

# Import the gsheet helper
from gsheet import get_sheet, fetch_student_by_qrcode, update_student_status_by_row

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Enhanced security configuration
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', secrets.token_hex(32)),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=False,  # Set to True in production with HTTPS
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=2),  # 2 hour session timeout
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,  # 16MB max file size
    JSONIFY_PRETTYPRINT_REGULAR=False  # Disable in production for performance
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Hardcoded coordinator credentials
COORDINATORS = {
    "Soumya": "PCE001",
    "Ankit": "PCE002", 
    "Riya": "PCE003",
    "Devraj": "PCE004"
}

# Rate limiting storage (in-memory for simplicity)
request_history = {}

def rate_limit(requests_per_minute=30):
    """Rate limiting decorator"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Get client IP
            client_ip = request.remote_addr
            
            # Clean old entries
            current_time = datetime.now()
            if client_ip in request_history:
                request_history[client_ip] = [
                    time for time in request_history[client_ip]
                    if current_time - time < timedelta(minutes=1)
                ]
            else:
                request_history[client_ip] = []
            
            # Check rate limit
            if len(request_history[client_ip]) >= requests_per_minute:
                logger.warning(f"Rate limit exceeded for IP: {client_ip}")
                return jsonify({'error': 'Rate limit exceeded. Please try again later.'}), 429
            
            # Add current request
            request_history[client_ip].append(current_time)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def handle_api_errors(f):
    """Global error handling decorator for API routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"API Error in {f.__name__}: {str(e)}", exc_info=True)
            return jsonify({'error': 'Internal server error'}), 500
    return decorated_function

def login_required(f):
    """Require authentication decorator"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('authenticated'):
            logger.warning(f"Unauthorized access attempt to {request.path}")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def validate_coordinator_input(name, coordinator_id):
    """Validate coordinator login input"""
    errors = []
    
    if not name or not isinstance(name, str) or name.strip() == '':
        errors.append('Name is required')
    elif len(name.strip()) > 50:
        errors.append('Name is too long (max 50 characters)')
    
    if not coordinator_id or not isinstance(coordinator_id, str) or coordinator_id.strip() == '':
        errors.append('Coordinator ID is required')
    elif len(coordinator_id.strip()) > 20:
        errors.append('Coordinator ID is too long (max 20 characters)')
    
    return {
        'is_valid': len(errors) == 0,
        'errors': errors,
        'clean_name': name.strip() if name else '',
        'clean_id': coordinator_id.strip().upper() if coordinator_id else ''
    }

@app.before_request
def before_request():
    """Execute before each request"""
    # Make session permanent
    session.permanent = True
    
    # Log request for debugging (but don't log sensitive data)
    if request.endpoint and 'static' not in request.endpoint:
        logger.info(f"Request: {request.method} {request.path} - IP: {request.remote_addr}")

@app.after_request
def after_request(response):
    """Execute after each request"""
    # Add security headers
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    # Disable caching for sensitive pages
    if request.path in ['/login', '/scan', '/result']:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    
    return response

@app.route('/')
def index():
    """Redirect to login page"""
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
@rate_limit(requests_per_minute=10)  # 10 login attempts per minute
def login():
    """Coordinator login page"""
    try:
        if request.method == 'POST':
            # Get and validate form data
            name = request.form.get('name', '').strip()
            coordinator_id = request.form.get('coordinator_id', '').strip()
            
            # Validate input
            validation = validate_coordinator_input(name, coordinator_id)
            
            if not validation['is_valid']:
                logger.warning(f"Login validation failed: {validation['errors']}")
                return render_template('login.html', error="Invalid input format"), 400
            
            clean_name = validation['clean_name']
            clean_id = validation['clean_id']
            
            # Validate coordinator credentials
            if clean_name in COORDINATORS and COORDINATORS[clean_name] == clean_id:
                # Successful login
                session['coordinator_name'] = clean_name
                session['coordinator_id'] = clean_id
                session['authenticated'] = True
                session['login_time'] = datetime.now().isoformat()
                session['session_id'] = secrets.token_hex(16)
                
                logger.info(f"Coordinator {clean_name} logged in successfully from IP: {request.remote_addr}")
                
                # Redirect to scan page
                return redirect(url_for('scan'))
            else:
                # Failed login
                logger.warning(f"Failed login attempt for name: {clean_name} from IP: {request.remote_addr}")
                return render_template('login.html', error="Invalid Name or Coordinator ID"), 401
        
        # GET request - show login form
        return render_template('login.html')
        
    except Exception as e:
        logger.error(f"Login error: {str(e)}", exc_info=True)
        return render_template('login.html', error="An error occurred during login"), 500

@app.route('/scan')
@login_required
def scan():
    """QR scanning page"""
    try:
        # Check session timeout
        login_time = session.get('login_time')
        if login_time:
            login_dt = datetime.fromisoformat(login_time)
            if datetime.now() - login_dt > app.config['PERMANENT_SESSION_LIFETIME']:
                session.clear()
                return redirect(url_for('login'))
        
        return render_template('scan.html', 
                             coordinator_name=session.get('coordinator_name'),
                             now=datetime.now())
        
    except Exception as e:
        logger.error(f"Scan page error: {str(e)}", exc_info=True)
        session.clear()
        return redirect(url_for('login'))

@app.route('/result', methods=['GET', 'POST'])
@login_required
def result():
    """Display student result page"""
    try:
        if request.method == 'POST':
            # Get data from form submission
            student_data_json = request.form.get('student_data', '{}')
            row_index = request.form.get('row_index', '')
            
            # Validate inputs
            if not student_data_json or not row_index:
                logger.warning("Missing student_data or row_index in result page")
                return redirect(url_for('scan'))
            
            try:
                student_data = json.loads(student_data_json)
                
                # Basic validation of student data
                if not isinstance(student_data, dict):
                    logger.warning("Invalid student data format")
                    return redirect(url_for('scan'))
                
                # Ensure row_index is valid
                try:
                    row_index_int = int(row_index)
                    if row_index_int < 1:
                        raise ValueError("Invalid row index")
                except ValueError:
                    logger.warning(f"Invalid row index: {row_index}")
                    return redirect(url_for('scan'))
                
                return render_template('result.html', 
                                    student_data=student_data,
                                    row_index=row_index_int,
                                    coordinator_name=session.get('coordinator_name'))
                
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error in result: {str(e)}")
                return redirect(url_for('scan'))
        
        # GET request - redirect to scan
        return redirect(url_for('scan'))
        
    except Exception as e:
        logger.error(f"Result page error: {str(e)}", exc_info=True)
        return redirect(url_for('scan'))

@app.route('/fetch', methods=['POST'])
@login_required
@handle_api_errors
@rate_limit(requests_per_minute=60)  # 60 scans per minute
def fetch_student():
    """Fetch student data by QR code"""
    # Validate coordinator authentication
    if not session.get('authenticated'):
        logger.warning("Unauthorized fetch attempt")
        return jsonify({'error': 'Authentication required'}), 401
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No JSON data provided'}), 400
    
    qr_string = data.get('qr_string', '').strip()
    
    if not qr_string:
        return jsonify({'error': 'QR string is required'}), 400
    
    # Validate QR string length
    if len(qr_string) > 1000:
        return jsonify({'error': 'QR string too long'}), 400
    
    # Log the fetch attempt
    coordinator_name = session.get('coordinator_name', 'Unknown')
    logger.info(f"Fetching student with QR: {qr_string[:50]}... by {coordinator_name}")
    
    try:
        # Fetch student data from Google Sheet
        student_data, row_index = fetch_student_by_qrcode(qr_string)
        
        if not student_data:
            logger.warning(f"QR code not found: {qr_string[:50]}...")
            return jsonify({'error': 'QR code not found in database'}), 404
        
        # Check if QR has already been used
        if student_data.get('Used', '').lower() == 'yes':
            used_by = student_data.get('Coordinator', 'Unknown')
            used_at = student_data.get('LastCheckedTime', 'Unknown time')
            logger.info(f"QR already used - Code: {qr_string[:50]}..., Used by: {used_by}, At: {used_at}")
            
            return jsonify({
                'error': 'QR already used',
                'used_by': used_by,
                'used_at': used_at
            }), 409
        
        # Return student data for display
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
                'Comment': student_data.get('Comment', ''),
                'LastCheckedTime': student_data.get('LastCheckedTime', ''),
                'Coordinator': student_data.get('Coordinator', ''),
                'Used': student_data.get('Used', '')
            }
        }
        
        student_name = student_data.get('StudentName', 'Unknown')
        student_id = student_data.get('StudentID', 'Unknown')
        logger.info(f"Found student: {student_name} (ID: {student_id}) at row {row_index}")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error fetching student: {str(e)}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/update', methods=['POST'])
@login_required
@handle_api_errors
@rate_limit(requests_per_minute=30)  # 30 updates per minute
def update_student():
    """Update student status after verification"""
    # Validate coordinator authentication
    if not session.get('authenticated'):
        return jsonify({'error': 'Authentication required'}), 401
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No JSON data provided'}), 400
    
    row_index = data.get('row_index')
    status = data.get('status', '')
    comment = data.get('comment', '')
    
    # Validate inputs
    if not row_index:
        return jsonify({'error': 'Row index is required'}), 400
    
    try:
        row_index_int = int(row_index)
        if row_index_int < 1:
            raise ValueError("Invalid row index")
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid row index'}), 400
    
    if not status or status not in ['Checked', 'Problematic', 'Suspicious', 'Absent']:
        return jsonify({'error': 'Valid status is required'}), 400
    
    if comment and len(comment) > 200:
        return jsonify({'error': 'Comment too long (max 200 characters)'}), 400
    
    coordinator_name = session.get('coordinator_name')
    
    logger.info(f"Updating row {row_index} with status: {status} by {coordinator_name}")
    
    try:
        # Update student record in Google Sheet
        success = update_student_status_by_row(
            row_index=row_index_int,
            status=status,
            comment=comment,
            coordinator=coordinator_name
        )
        
        if success:
            # Log the successful update
            logger.info(f"Successfully updated row {row_index_int} - Status: {status}, Coordinator: {coordinator_name}")
            
            # Clear session to force re-authentication for next scan
            session.clear()
            
            return jsonify({
                'success': True, 
                'message': 'Status updated successfully',
                'coordinator': coordinator_name,
                'timestamp': datetime.now().isoformat()
            })
        else:
            logger.error(f"Failed to update row {row_index_int}")
            return jsonify({'error': 'Failed to update record in database'}), 500
            
    except Exception as e:
        logger.error(f"Error updating student: {str(e)}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/logout')
def logout():
    """Explicit logout endpoint"""
    coordinator_name = session.get('coordinator_name', 'Unknown')
    session.clear()
    logger.info(f"Coordinator {coordinator_name} logged out")
    return redirect(url_for('login'))

@app.route('/health')
def health_check():
    """Comprehensive health check endpoint"""
    try:
        # Test database connection
        sheet = get_sheet()
        row_count = len(sheet.get_all_values())
        
        health_data = {
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'service': 'FRESH CHECKS QR Gate',
            'version': '2.0.0',
            'database_connection': 'ok',
            'total_records': row_count,
            'uptime': str(datetime.now() - app_start_time)
        }
        
        return jsonify(health_data)
        
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/debug/sheet')
def debug_sheet():
    """Debug endpoint to check sheet structure"""
    try:
        from gsheet import debug_sheet_structure
        result = debug_sheet_structure()
        return jsonify({'message': 'Check logs for sheet structure details', 'success': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/debug/test-connection')
def test_connection():
    """Test Google Sheets connection"""
    try:
        from gsheet import test_connection
        result = test_connection()
        return jsonify({'message': 'Connection test completed', 'success': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({'error': 'Method not allowed'}), 405

@app.errorhandler(429)
def rate_limit_exceeded(error):
    return jsonify({'error': 'Rate limit exceeded. Please try again later.'}), 429

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {str(error)}")
    return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(Exception)
def handle_unexpected_error(error):
    """Global unexpected error handler"""
    logger.error(f"Unexpected error: {str(error)}", exc_info=True)
    return jsonify({'error': 'An unexpected error occurred'}), 500

# Initialize application
def initialize_app():
    """Initialize the application with required setup"""
    global app_start_time
    app_start_time = datetime.now()
    
    try:
        # Initialize Google Sheets connection
        sheet = get_sheet()
        
        # Test connection by getting data
        test_data = sheet.get_all_values()
        logger.info(f"✅ Google Sheets connection established successfully")
        logger.info(f"📊 Sheet contains {len(test_data)} rows")
        
        # Log startup information
        logger.info(f"🚀 FRESH CHECKS application started successfully")
        logger.info(f"📝 Coordinators configured: {len(COORDINATORS)}")
        logger.info(f"🔐 Session timeout: {app.config['PERMANENT_SESSION_LIFETIME']}")
        
        # Log column mapping info
        from gsheet import get_column_mapping
        column_mapping = get_column_mapping()
        logger.info(f"📋 Using column mapping: {len(column_mapping)} columns")
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize Google Sheets: {str(e)}")
        logger.error("Application may not function properly without Google Sheets connection")

# Initialize the application
if __name__ == '__main__':
    initialize_app()
    
    # Get port from environment or default to 5000
    port = int(os.environ.get('PORT', 5000))
    
    # Determine if we're in production
    debug_mode = os.environ.get('FLASK_ENV') != 'production'
    
    if debug_mode:
        logger.info("🛠️  Starting in DEVELOPMENT mode")
        # Enable debug endpoints in development
        @app.route('/debug/columns')
        def debug_columns():
            from gsheet import get_column_mapping
            return jsonify({'column_mapping': get_column_mapping()})
        
        app.run(host='0.0.0.0', port=port, debug=True)
    else:
        logger.info("🚀 Starting in PRODUCTION mode")
        app.run(host='0.0.0.0', port=port, debug=False)
else:
    # For Gunicorn deployment
    initialize_app()