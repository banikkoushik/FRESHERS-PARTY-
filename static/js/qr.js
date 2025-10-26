// QR Scanner functionality for FRESH CHECKS
let html5QrCode = null;
let currentCameraId = null;
let isScanning = false;

// Camera status updates
function updateCameraStatus(message, type = 'info') {
    const statusEl = document.getElementById('camera-status');
    if (statusEl) {
        statusEl.innerHTML = `<div class="status-${type}">${message}</div>`;
    }
}

// Initialize camera when page loads
function initializeCamera() {
    // Check if we're on the scan page
    if (!document.getElementById('qr-reader')) {
        return;
    }
    
    // Auto-start camera with a small delay
    setTimeout(() => {
        startCamera();
    }, 1000);
}

async function startCamera() {
    if (isScanning) {
        console.log('Camera is already scanning');
        return;
    }
    
    try {
        updateCameraStatus('🔄 Starting camera...', 'loading');
        console.log('Attempting to start camera...');
        
        // Hide start button, show stop button
        const startBtn = document.getElementById('start-camera-btn');
        const stopBtn = document.getElementById('stop-camera-btn');
        const switchBtn = document.getElementById('switch-camera-btn');
        
        if (startBtn) startBtn.style.display = 'none';
        if (stopBtn) stopBtn.style.display = 'inline-block';
        
        // Create scanner instance if it doesn't exist
        if (!html5QrCode) {
            html5QrCode = new Html5Qrcode("qr-reader");
        }
        
        // Get available cameras
        const cameras = await Html5Qrcode.getCameras();
        console.log('Available cameras:', cameras);
        
        if (!cameras || cameras.length === 0) {
            throw new Error("No cameras found on this device");
        }
        
        // Camera selection logic
        let cameraId = cameras[0].id;
        
        // Prefer rear camera on mobile devices
        if (cameras.length > 1) {
            const rearCamera = cameras.find(cam => 
                cam.label.toLowerCase().includes('back') || 
                cam.label.toLowerCase().includes('rear') ||
                cam.label.toLowerCase().includes('environment') ||
                cam.label.includes('2') // Often rear camera is camera2
            );
            
            if (rearCamera) {
                cameraId = rearCamera.id;
                console.log('Selected rear camera:', rearCamera.label);
            } else {
                console.log('Using default camera:', cameras[0].label);
            }
        }
        
        currentCameraId = cameraId;
        
        // Camera configuration for different devices
        const config = {
            fps: 10,
            qrbox: { 
                width: 250, 
                height: 250 
            },
            aspectRatio: 1.0,
            focusMode: "continuous"
        };
        
        console.log('Starting camera with config:', config);
        
        // Start scanning
        await html5QrCode.start(
            cameraId,
            config,
            onScanSuccess,
            onScanFailure
        );
        
        isScanning = true;
        updateCameraStatus('✅ Camera active - Point camera at QR code', 'success');
        console.log('Camera started successfully');
        
        // Show switch camera button if multiple cameras available
        if (cameras.length > 1 && switchBtn) {
            switchBtn.style.display = 'inline-block';
        }
        
    } catch (error) {
        console.error('Camera startup error:', error);
        handleCameraError(error);
    }
}

function stopCamera() {
    if (!html5QrCode || !isScanning) {
        console.log('No active camera to stop');
        return;
    }
    
    console.log('Stopping camera...');
    
    html5QrCode.stop().then(() => {
        isScanning = false;
        updateCameraStatus('⏹️ Camera stopped', 'info');
        console.log('Camera stopped successfully');
        
        // Update UI
        const startBtn = document.getElementById('start-camera-btn');
        const stopBtn = document.getElementById('stop-camera-btn');
        const switchBtn = document.getElementById('switch-camera-btn');
        
        if (startBtn) startBtn.style.display = 'inline-block';
        if (stopBtn) stopBtn.style.display = 'none';
        if (switchBtn) switchBtn.style.display = 'none';
        
    }).catch(error => {
        console.error('Error stopping camera:', error);
        updateCameraStatus('❌ Error stopping camera', 'error');
    });
}

async function switchCamera() {
    if (!html5QrCode || !isScanning) {
        console.log('No active camera to switch');
        return;
    }
    
    try {
        updateCameraStatus('🔄 Switching camera...', 'loading');
        
        const cameras = await Html5Qrcode.getCameras();
        if (cameras.length < 2) {
            updateCameraStatus('ℹ️ Only one camera available', 'info');
            return;
        }
        
        // Find next camera
        const currentIndex = cameras.findIndex(cam => cam.id === currentCameraId);
        const nextIndex = (currentIndex + 1) % cameras.length;
        const nextCameraId = cameras[nextIndex].id;
        
        console.log(`Switching from camera ${currentIndex} to ${nextIndex}`);
        
        // Stop current camera
        await html5QrCode.stop();
        
        // Start with new camera
        await html5QrCode.start(
            nextCameraId,
            {
                fps: 10,
                qrbox: { width: 250, height: 250 },
                aspectRatio: 1.0
            },
            onScanSuccess,
            onScanFailure
        );
        
        currentCameraId = nextCameraId;
        updateCameraStatus(`✅ Switched to ${cameras[nextIndex].label}`, 'success');
        
    } catch (error) {
        console.error('Camera switch error:', error);
        updateCameraStatus('❌ Error switching camera', 'error');
        
        // Try to restart with original camera
        try {
            await startCamera();
        } catch (retryError) {
            console.error('Failed to restart camera after switch error:', retryError);
        }
    }
}

function onScanSuccess(decodedText, decodedResult) {
    console.log(`QR Scan successful: ${decodedText}`);
    
    // Visual feedback
    updateCameraStatus('✅ QR Code Detected!', 'success');
    
    // Stop scanner after successful scan
    if (html5QrCode && isScanning) {
        html5QrCode.stop().then(() => {
            isScanning = false;
            console.log('Camera stopped after successful scan');
        }).catch(console.error);
    }
    
    // Process the QR code
    processQRCode(decodedText);
}

function onScanFailure(error) {
    // Only log unexpected errors
    if (error && !error.toString().includes('No QR code found')) {
        console.log('Scan error:', error);
    }
}

function processQRCode(qrString) {
    console.log('Processing QR code:', qrString);
    
    if (!qrString || qrString.trim() === '') {
        showNotification('Invalid QR code', 'error');
        restartCamera();
        return;
    }
    
    // Show processing notification
    showNotification('Processing QR code...', 'info');
    
    // Send to server
    fetchStudentData(qrString);
}

function restartCamera() {
    console.log('Restarting camera...');
    setTimeout(() => {
        if (!isScanning) {
            startCamera().catch(error => {
                console.error('Failed to restart camera:', error);
            });
        }
    }, 2000);
}

function handleCameraError(error) {
    console.error('Camera setup failed:', error);
    
    let errorMessage = '❌ Camera access failed';
    let detailedMessage = error.toString();
    
    if (error.name === 'NotAllowedError') {
        errorMessage = '❌ Camera permission denied';
        detailedMessage = 'Please allow camera access in your browser settings and refresh the page.';
    } else if (error.name === 'NotFoundError') {
        errorMessage = '❌ No camera found';
        detailedMessage = 'This device does not have a camera or it is not accessible.';
    } else if (error.name === 'NotSupportedError') {
        errorMessage = '❌ Camera not supported';
        detailedMessage = 'Your browser does not support camera access.';
    } else if (error.name === 'NotReadableError') {
        errorMessage = '❌ Camera in use';
        detailedMessage = 'Camera is already in use by another application.';
    } else if (error.message && error.message.includes('No cameras found')) {
        errorMessage = '❌ No camera detected';
        detailedMessage = 'No cameras were found on this device.';
    }
    
    updateCameraStatus(`${errorMessage} - ${detailedMessage}`, 'error');
    
    // Show start button for retry
    const startBtn = document.getElementById('start-camera-btn');
    const stopBtn = document.getElementById('stop-camera-btn');
    const switchBtn = document.getElementById('switch-camera-btn');
    
    if (startBtn) startBtn.style.display = 'inline-block';
    if (stopBtn) stopBtn.style.display = 'none';
    if (switchBtn) switchBtn.style.display = 'none';
}

// Make functions globally available
window.startCamera = startCamera;
window.stopCamera = stopCamera;
window.switchCamera = switchCamera;
window.initializeCamera = initializeCamera;

// Initialize when document is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeCamera);
} else {
    initializeCamera();
}
