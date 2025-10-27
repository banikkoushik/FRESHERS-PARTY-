// QR Scanner functionality for FRESH CHECKS - Enhanced Version
let videoStream = null;
let currentFacingMode = 'environment'; // Prefer rear camera
let isScanning = false;
let animationFrame = null;
let lastScanTime = 0;
let cameraRetryCount = 0;
let scanTimeout = null;

// Scan configuration
const SCAN_CONFIG = {
    SCAN_INTERVAL: 300, // ms between scans to reduce CPU usage
    SCAN_COOLDOWN: 2000, // 2 seconds between successful scans
    MAX_RETRIES: 3,
    SCAN_TIMEOUT: 5 * 60 * 1000, // 5 minutes auto-stop
    CAMERA_RETRY_DELAY: 1000 // 1 second between retries
};

// Scanning statistics
const scanStats = {
    totalScans: 0,
    successfulScans: 0,
    failedScans: 0,
    cameraStarts: 0,
    cameraErrors: 0,
    scanStartTime: null,
    
    startSession() {
        this.scanStartTime = Date.now();
        this.totalScans = 0;
        this.successfulScans = 0;
        this.failedScans = 0;
        this.cameraStarts = 0;
        this.cameraErrors = 0;
    },
    
    recordScan(success) {
        this.totalScans++;
        if (success) this.successfulScans++;
        else this.failedScans++;
        
        console.log('Scan Statistics:', this.getSummary());
    },
    
    recordCameraStart() {
        this.cameraStarts++;
    },
    
    recordCameraError() {
        this.cameraErrors++;
    },
    
    getSessionDuration() {
        return this.scanStartTime ? Date.now() - this.scanStartTime : 0;
    },
    
    getSummary() {
        const duration = this.getSessionDuration();
        const mins = Math.floor(duration / 60000);
        const secs = Math.floor((duration % 60000) / 1000);
        
        return {
            totalScans: this.totalScans,
            successfulScans: this.successfulScans,
            failedScans: this.failedScans,
            successRate: this.totalScans > 0 ? (this.successfulScans / this.totalScans * 100).toFixed(1) : 0,
            sessionDuration: `${mins}m ${secs}s`,
            cameraStarts: this.cameraStarts,
            cameraErrors: this.cameraErrors
        };
    }
};

// Camera status updates
function updateCameraStatus(message, type = 'info') {
    const statusEl = document.getElementById('camera-status');
    if (statusEl) {
        statusEl.innerHTML = `<div class="status-${type}">${message}</div>`;
    }
}

// Check if jsQR library is loaded
function isLibraryLoaded() {
    if (typeof jsQR === 'undefined') {
        updateCameraStatus('❌ QR scanner library not loaded. Please refresh the page.', 'error');
        return false;
    }
    return true;
}

// Enhanced camera detection
async function getBestCamera() {
    try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const videoDevices = devices.filter(device => device.kind === 'videoinput');
        
        console.log('Available cameras:', videoDevices);
        
        if (videoDevices.length === 0) {
            throw new Error('No cameras found');
        }
        
        // Prefer rear-facing cameras
        const rearCamera = videoDevices.find(device => 
            device.label.toLowerCase().includes('back') ||
            device.label.toLowerCase().includes('rear') ||
            device.label.toLowerCase().includes('environment') ||
            device.label.includes('2') // Often rear camera is camera2
        );
        
        if (rearCamera) {
            console.log('Selected rear camera:', rearCamera.label);
            return { device: rearCamera, facingMode: 'environment' };
        }
        
        // Fallback to first available camera
        console.log('Using default camera:', videoDevices[0].label);
        return { device: videoDevices[0], facingMode: 'user' };
        
    } catch (error) {
        console.warn('Could not enumerate devices:', error);
        return { device: null, facingMode: 'environment' };
    }
}

// Check camera permissions
async function checkCameraPermissions() {
    try {
        if (!navigator.permissions || !navigator.permissions.query) {
            return 'unknown'; // Permission API not supported
        }
        
        const permissions = await navigator.permissions.query({ name: 'camera' });
        return permissions.state;
    } catch (error) {
        console.warn('Permission API not supported:', error);
        return 'unknown';
    }
}

// Enhanced camera startup with retry mechanism
async function startCameraWithRetry() {
    try {
        const permissionState = await checkCameraPermissions();
        
        if (permissionState === 'denied') {
            showNotification('Camera permission permanently denied. Please enable in browser settings.', 'error', 0);
            handleCameraError(new Error('Permission denied'));
            return;
        }
        
        await startCamera();
        cameraRetryCount = 0; // Reset on success
        
    } catch (error) {
        cameraRetryCount++;
        
        if (cameraRetryCount <= SCAN_CONFIG.MAX_RETRIES) {
            console.log(`Camera retry attempt ${cameraRetryCount}/${SCAN_CONFIG.MAX_RETRIES}`);
            updateCameraStatus(`🔄 Camera retry ${cameraRetryCount}/${SCAN_CONFIG.MAX_RETRIES}...`, 'loading');
            
            setTimeout(() => {
                startCameraWithRetry();
            }, SCAN_CONFIG.CAMERA_RETRY_DELAY * cameraRetryCount);
            
        } else {
            console.error('Max camera retries exceeded');
            handleCameraError(error);
        }
    }
}

async function startCamera() {
    if (isScanning) {
        console.log('Camera is already scanning');
        return;
    }
    
    // Check if library is loaded
    if (!isLibraryLoaded()) {
        return;
    }
    
    try {
        updateCameraStatus('🔄 Requesting camera access...', 'loading');
        console.log('Requesting camera permission...');
        
        // Update statistics
        scanStats.recordCameraStart();
        
        // Hide start button, show stop button
        document.getElementById('start-camera-btn').style.display = 'none';
        document.getElementById('stop-camera-btn').style.display = 'inline-block';
        
        const video = document.getElementById('video');
        const canvas = document.getElementById('canvas');
        const canvasContext = canvas.getContext('2d');
        
        // Get best camera
        const cameraInfo = await getBestCamera();
        currentFacingMode = cameraInfo.facingMode;
        
        // Camera constraints based on device type
        const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
        const constraints = {
            video: {
                facingMode: currentFacingMode,
                width: { ideal: isMobile ? 1280 : 1920 },
                height: { ideal: isMobile ? 720 : 1080 },
                frameRate: { ideal: isMobile ? 15 : 30 }
            }
        };
        
        // If we have a specific device ID, use it
        if (cameraInfo.device && cameraInfo.device.deviceId) {
            constraints.video.deviceId = { exact: cameraInfo.device.deviceId };
        }
        
        console.log('Camera constraints:', constraints);
        
        // Get camera stream
        const stream = await navigator.mediaDevices.getUserMedia(constraints);
        
        videoStream = stream;
        video.srcObject = stream;
        
        // Wait for video to be ready
        await new Promise((resolve, reject) => {
            video.onloadedmetadata = () => {
                video.play().then(resolve).catch(reject);
            };
            video.onerror = reject;
            
            // Timeout for video readiness
            setTimeout(() => reject(new Error('Video loading timeout')), 10000);
        });
        
        // Set canvas size to match video
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        
        isScanning = true;
        updateCameraStatus('✅ Camera active - Point at QR code to scan', 'success');
        
        // Show switch camera button if multiple cameras available
        const devices = await navigator.mediaDevices.enumerateDevices();
        const videoDevices = devices.filter(device => device.kind === 'videoinput');
        if (videoDevices.length > 1) {
            document.getElementById('switch-camera-btn').style.display = 'inline-block';
        }
        
        // Start scan timeout
        startScanTimeout();
        
        // Start QR scanning loop
        function scanQR() {
            if (!isScanning) return;
            
            const now = Date.now();
            
            // Throttle scanning to reduce CPU usage
            if (now - lastScanTime < SCAN_CONFIG.SCAN_INTERVAL) {
                animationFrame = requestAnimationFrame(scanQR);
                return;
            }
            lastScanTime = now;
            
            if (video.readyState === video.HAVE_ENOUGH_DATA) {
                try {
                    canvasContext.drawImage(video, 0, 0, canvas.width, canvas.height);
                    const imageData = canvasContext.getImageData(0, 0, canvas.width, canvas.height);
                    const code = jsQR(imageData.data, imageData.width, imageData.height, {
                        inversionAttempts: "dontInvert",
                    });
                    
                    if (code) {
                        console.log('QR Code found:', code.data);
                        stopCamera();
                        showScanFeedback();
                        processQRCode(code.data);
                        return;
                    }
                } catch (error) {
                    console.error('Scan processing error:', error);
                }
            }
            
            animationFrame = requestAnimationFrame(scanQR);
        }
        
        scanQR();
        
    } catch (error) {
        console.error('Camera startup error:', error);
        throw error; // Re-throw for retry mechanism
    }
}

function stopCamera() {
    if (!isScanning) {
        console.log('No active camera to stop');
        return;
    }
    
    console.log('Stopping camera...');
    
    isScanning = false;
    
    // Stop scan timeout
    stopScanTimeout();
    
    // Cancel animation frame
    if (animationFrame) {
        cancelAnimationFrame(animationFrame);
        animationFrame = null;
    }
    
    // Stop video stream
    if (videoStream) {
        videoStream.getTracks().forEach(track => {
            track.stop();
        });
        videoStream = null;
    }
    
    // Clear video element
    const video = document.getElementById('video');
    if (video) {
        video.srcObject = null;
    }
    
    updateCameraStatus('⏹️ Camera stopped - Click "Start Camera" to scan again', 'info');
    
    // Update UI
    document.getElementById('start-camera-btn').style.display = 'inline-block';
    document.getElementById('stop-camera-btn').style.display = 'none';
    document.getElementById('switch-camera-btn').style.display = 'none';
}

async function switchCamera() {
    if (!isScanning) return;
    
    try {
        updateCameraStatus('🔄 Switching camera...', 'loading');
        
        // Stop current camera
        stopCamera();
        
        // Switch facing mode
        currentFacingMode = currentFacingMode === 'environment' ? 'user' : 'environment';
        
        console.log(`Switching to ${currentFacingMode} camera`);
        
        // Restart camera with new facing mode
        await startCameraWithRetry();
        
    } catch (error) {
        console.error('Switch error:', error);
        updateCameraStatus('❌ Error switching camera', 'error');
        
        // Try to restart with original camera
        try {
            await startCameraWithRetry();
        } catch (retryError) {
            console.error('Failed to restart camera after switch error:', retryError);
        }
    }
}

// Scan timeout management
function startScanTimeout() {
    stopScanTimeout();
    scanTimeout = setTimeout(() => {
        if (isScanning) {
            console.log('Scan timeout reached - stopping camera');
            showNotification('Scanning timeout - camera stopped to save battery', 'info');
            stopCamera();
        }
    }, SCAN_CONFIG.SCAN_TIMEOUT);
}

function stopScanTimeout() {
    if (scanTimeout) {
        clearTimeout(scanTimeout);
        scanTimeout = null;
    }
}

// Visual feedback for successful scan
function showScanFeedback() {
    const scannerWrapper = document.querySelector('.scanner-wrapper');
    if (!scannerWrapper) return;
    
    const feedback = document.createElement('div');
    feedback.className = 'scan-feedback';
    feedback.textContent = '✅ QR Code Detected!';
    scannerWrapper.appendChild(feedback);
    
    setTimeout(() => {
        if (feedback.parentNode) {
            feedback.remove();
        }
    }, 2000);
}

// Enhanced QR code validation
function validateQRCode(qrString) {
    if (!qrString || typeof qrString !== 'string') {
        return { valid: false, reason: 'Invalid QR format' };
    }
    
    // Trim and clean the string
    const cleanString = qrString.trim();
    
    if (cleanString.length === 0) {
        return { valid: false, reason: 'Empty QR code' };
    }
    
    if (cleanString.length > 1000) {
        return { valid: false, reason: 'QR code too long' };
    }
    
    // Check for expected patterns (adjust based on your QR format)
    const expectedPatterns = [
        /^STUDENT_\d+$/, // Example: STUDENT_12345
        /^[A-Za-z0-9_\-]{5,50}$/, // Alphanumeric with underscores and dashes
        // Add your specific patterns here
    ];
    
    const isValid = expectedPatterns.some(pattern => pattern.test(cleanString));
    
    return {
        valid: isValid,
        cleanData: cleanString,
        reason: isValid ? 'Valid' : 'Unexpected QR code format'
    };
}

function processQRCode(qrString) {
    console.log('Processing QR code:', qrString);
    
    const validation = validateQRCode(qrString);
    
    if (!validation.valid) {
        showNotification(`Invalid QR code: ${validation.reason}`, 'error');
        restartCamera();
        return;
    }
    
    // Check scan cooldown
    const now = Date.now();
    if (now - lastScanTime < SCAN_CONFIG.SCAN_COOLDOWN) {
        console.log('Scan ignored - too frequent');
        restartCamera();
        return;
    }
    
    lastScanTime = now;
    
    // Show processing notification
    showNotification('Processing QR code...', 'info');
    
    // Update statistics
    scanStats.recordScan(true);
    
    // Send to server
    fetchStudentData(validation.cleanData);
}

function restartCamera() {
    console.log('Restarting camera in 3 seconds...');
    
    // Update statistics for failed scan
    scanStats.recordScan(false);
    
    setTimeout(() => {
        if (!isScanning) {
            startCameraWithRetry().catch(error => {
                console.error('Failed to restart camera:', error);
            });
        }
    }, 3000);
}

function handleCameraError(error) {
    console.error('Camera setup failed:', error);
    
    // Update statistics
    scanStats.recordCameraError();
    
    let errorMessage = '❌ Camera access failed';
    let detailedMessage = '';
    
    if (error.name === 'NotAllowedError') {
        errorMessage = '❌ Camera permission denied';
        detailedMessage = 'Please allow camera access when prompted by your browser.';
    } else if (error.name === 'NotFoundError') {
        errorMessage = '❌ No camera found';
        detailedMessage = 'This device does not have a camera or it is not accessible.';
    } else if (error.name === 'NotSupportedError') {
        errorMessage = '❌ Camera not supported';
        detailedMessage = 'Your browser does not support camera access. Try Chrome or Safari.';
    } else if (error.name === 'NotReadableError') {
        errorMessage = '❌ Camera in use';
        detailedMessage = 'Camera is already in use by another application.';
    } else if (error.message && error.message.includes('No cameras found')) {
        errorMessage = '❌ No camera detected';
        detailedMessage = 'No cameras were found on this device.';
    } else if (error.message && error.message.includes('Video loading timeout')) {
        errorMessage = '❌ Camera timeout';
        detailedMessage = 'Camera took too long to initialize. Please try again.';
    } else {
        detailedMessage = error.toString();
    }
    
    updateCameraStatus(`${errorMessage} - ${detailedMessage}`, 'error');
    
    // Show start button for retry
    document.getElementById('start-camera-btn').style.display = 'inline-block';
    document.getElementById('stop-camera-btn').style.display = 'none';
    document.getElementById('switch-camera-btn').style.display = 'none';
}

// Enhanced camera recovery
async function recoverCamera() {
    try {
        if (isScanning) {
            await stopCamera();
        }
        
        // Clear any existing scanner
        const scannerWrapper = document.querySelector('.scanner-wrapper');
        if (scannerWrapper) {
            scannerWrapper.innerHTML = `
                <video id="video" class="video-element" playsinline></video>
                <canvas id="canvas" class="canvas-element" style="display: none;"></canvas>
                <div class="scanning-overlay">
                    <div class="scan-box"></div>
                </div>
            `;
        }
        
        await startCameraWithRetry();
    } catch (error) {
        console.error('Camera recovery failed:', error);
        handleCameraError(error);
    }
}

// Battery and performance optimizations
function setupPerformanceOptimizations() {
    // Reduce scanning when page is not visible
    document.addEventListener('visibilitychange', () => {
        if (document.hidden && isScanning) {
            console.log('Page hidden - reducing scan frequency');
            // We're already throttling scans, so no additional action needed
        }
    });
    
    // Stop camera when page is not visible to save battery
    document.addEventListener('visibilitychange', () => {
        if (document.hidden && isScanning) {
            console.log('Page hidden - stopping camera to save battery');
            stopCamera();
        }
    });
}

// Manual input handling
function setupManualInput() {
    const manualInput = document.getElementById('manual-code-input');
    const submitBtn = document.getElementById('manual-submit-btn');
    
    if (manualInput && submitBtn) {
        manualInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                submitManualCode();
            }
        });
        
        submitBtn.addEventListener('click', submitManualCode);
    }
}

function submitManualCode() {
    const manualInput = document.getElementById('manual-code-input');
    const code = manualInput.value.trim();
    
    if (!code) {
        showNotification('Please enter a code', 'error');
        return;
    }
    
    // Stop camera when using manual input
    if (isScanning) {
        stopCamera();
    }
    
    processQRCode(code);
    manualInput.value = ''; // Clear input
}

// Analytics and debugging
function logScanSession() {
    const stats = scanStats.getSummary();
    console.group('📊 Scan Session Summary');
    console.log(`Duration: ${stats.sessionDuration}`);
    console.log(`Total Scans: ${stats.totalScans}`);
    console.log(`Successful: ${stats.successfulScans}`);
    console.log(`Failed: ${stats.failedScans}`);
    console.log(`Success Rate: ${stats.successRate}%`);
    console.log(`Camera Starts: ${stats.cameraStarts}`);
    console.log(`Camera Errors: ${stats.cameraErrors}`);
    console.groupEnd();
}

// Initialize scanner
function initializeScanner() {
    // Check if we're on the scan page
    if (!document.getElementById('video')) {
        return;
    }
    
    console.log('Initializing QR Scanner...');
    
    // Start statistics session
    scanStats.startSession();
    
    // Setup performance optimizations
    setupPerformanceOptimizations();
    
    // Setup manual input if available
    setupManualInput();
    
    // Auto-start camera with a small delay
    setTimeout(() => {
        startCameraWithRetry().catch(error => {
            console.log('Auto-start failed, waiting for user interaction');
        });
    }, 1000);
}

// Make functions globally available
window.startCamera = startCameraWithRetry;
window.stopCamera = stopCamera;
window.switchCamera = switchCamera;
window.restartCamera = restartCamera;
window.recoverCamera = recoverCamera;
window.submitManualCode = submitManualCode;
window.initializeScanner = initializeScanner;

// Export statistics for debugging
window.getScanStats = () => scanStats.getSummary();
window.logScanSession = logScanSession;

// Initialize when document is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeScanner);
} else {
    initializeScanner();
}

// Global error handling for scanner
window.addEventListener('error', function(e) {
    if (e.message && e.message.includes('QR') || e.message.includes('camera') || e.message.includes('scan')) {
        console.error('Scanner error:', e.error);
        showNotification('Scanner error occurred', 'error');
    }
});

window.addEventListener('unhandledrejection', function(e) {
    if (e.reason && (e.reason.message.includes('QR') || e.reason.message.includes('camera') || e.reason.message.includes('scan'))) {
        console.error('Unhandled scanner promise rejection:', e.reason);
        showNotification('Scanner error occurred', 'error');
        e.preventDefault();
    }
});