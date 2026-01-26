/**
 * Cat/Ball Tracker - Frontend JavaScript
 * Handles tab switching, mode toggle, perimeter drawing, and status updates
 */

// ============================================================================
// Tab Navigation
// ============================================================================
document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    initModeToggle();
    initPerimeterEditor();
    initCalibrationEditor();
    initMiniMap();
    initPerformanceControls();
    initHelpModal();
    initStatusUpdates();
    loadCurrentState();
});

// ============================================================================
// Help Modal
// ============================================================================
function initHelpModal() {
    const helpBtn = document.getElementById('help-btn');
    const helpModal = document.getElementById('help-modal');
    const closeBtn = document.getElementById('close-help');
    
    if (!helpBtn || !helpModal) return;
    
    // Open modal
    helpBtn.addEventListener('click', () => {
        helpModal.classList.add('active');
        document.body.style.overflow = 'hidden';
    });
    
    // Close modal - X button
    closeBtn.addEventListener('click', () => {
        helpModal.classList.remove('active');
        document.body.style.overflow = '';
    });
    
    // Close modal - click outside
    helpModal.addEventListener('click', (e) => {
        if (e.target === helpModal) {
            helpModal.classList.remove('active');
            document.body.style.overflow = '';
        }
    });
    
    // Close modal - Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && helpModal.classList.contains('active')) {
            helpModal.classList.remove('active');
            document.body.style.overflow = '';
        }
    });
}

function initTabs() {
    // Main tabs
    const tabButtons = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    
    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            // Remove active from all
            tabButtons.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            
            // Add active to clicked
            btn.classList.add('active');
            const tabId = btn.dataset.tab + '-tab';
            document.getElementById(tabId).classList.add('active');
        });
    });
    
    // Sub-tabs within Control Panel
    const subTabButtons = document.querySelectorAll('.sub-tab-btn');
    const subTabContents = document.querySelectorAll('.sub-tab-content');
    
    subTabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            // Remove active from all sub-tabs
            subTabButtons.forEach(b => b.classList.remove('active'));
            subTabContents.forEach(c => c.classList.remove('active'));
            
            // Add active to clicked
            btn.classList.add('active');
            const subTabId = btn.dataset.subtab + '-subtab';
            document.getElementById(subTabId).classList.add('active');
            
            // Refresh snapshots when switching to calibration or detection tab
            if (btn.dataset.subtab === 'calibration') {
                captureCalibrationSnapshot();
            } else if (btn.dataset.subtab === 'detection') {
                capturePerimeterSnapshot();
            }
        });
    });
}

// ============================================================================
// Mode Toggle (Cat / Ball)
// ============================================================================
function initModeToggle() {
    const catBtn = document.getElementById('mode-cat');
    const ballBtn = document.getElementById('mode-ball');
    
    catBtn.addEventListener('click', () => setMode('cat'));
    ballBtn.addEventListener('click', () => setMode('ball'));
}

async function setMode(mode) {
    try {
        const response = await fetch('/api/mode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode })
        });
        
        if (response.ok) {
            updateModeUI(mode);
        } else {
            console.error('Failed to set mode');
        }
    } catch (error) {
        console.error('Error setting mode:', error);
    }
}

function updateModeUI(mode) {
    const catBtn = document.getElementById('mode-cat');
    const ballBtn = document.getElementById('mode-ball');
    const modeDisplay = document.getElementById('mode-display');
    const currentMode = document.getElementById('current-mode');
    
    catBtn.classList.toggle('active', mode === 'cat');
    ballBtn.classList.toggle('active', mode === 'ball');
    
    const modeLabel = mode.charAt(0).toUpperCase() + mode.slice(1);
    modeDisplay.textContent = `Mode: ${modeLabel}`;
    currentMode.textContent = modeLabel;
}

// ============================================================================
// Perimeter Editor
// ============================================================================
let perimeterPoints = [];
let perimeterCanvas, perimeterCtx;
let perimeterImage = null;

function initPerimeterEditor() {
    perimeterCanvas = document.getElementById('perimeter-canvas');
    if (!perimeterCanvas) return;
    
    perimeterCtx = perimeterCanvas.getContext('2d');
    
    // Handle canvas clicks
    perimeterCanvas.addEventListener('click', (e) => {
        const rect = perimeterCanvas.getBoundingClientRect();
        const scaleX = perimeterCanvas.width / rect.width;
        const scaleY = perimeterCanvas.height / rect.height;
        
        const x = Math.round((e.clientX - rect.left) * scaleX);
        const y = Math.round((e.clientY - rect.top) * scaleY);
        
        perimeterPoints.push([x, y]);
        drawPerimeter();
        updatePointsCount();
    });
    
    // Clear button
    document.getElementById('clear-perimeter').addEventListener('click', () => {
        perimeterPoints = [];
        drawPerimeter();
        updatePointsCount();
    });
    
    // Save button
    document.getElementById('save-perimeter').addEventListener('click', savePerimeter);
    
    // Refresh snapshot button
    const refreshBtn = document.getElementById('refresh-perimeter-snapshot');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', capturePerimeterSnapshot);
    }
    
    // Initial snapshot
    capturePerimeterSnapshot();
}

function capturePerimeterSnapshot() {
    // Capture a snapshot from the video feed for perimeter drawing
    perimeterImage = new Image();
    perimeterImage.crossOrigin = 'anonymous';
    
    const timestamp = new Date().getTime();
    perimeterImage.src = `/video_feed?snapshot=1&t=${timestamp}`;
    
    perimeterImage.onload = () => {
        drawPerimeter();
    };
    
    perimeterImage.onerror = () => {
        console.log('Could not load camera snapshot for perimeter');
        perimeterImage = null;
        drawPerimeter();
    };
}

function drawPerimeter() {
    if (!perimeterCtx) return;
    
    // Clear canvas
    perimeterCtx.fillStyle = '#1a1a2e';
    perimeterCtx.fillRect(0, 0, perimeterCanvas.width, perimeterCanvas.height);
    
    // Draw camera snapshot as background if available
    if (perimeterImage && perimeterImage.complete && perimeterImage.naturalWidth > 0) {
        perimeterCtx.drawImage(perimeterImage, 0, 0, perimeterCanvas.width, perimeterCanvas.height);
        
        // Add semi-transparent overlay for better visibility
        perimeterCtx.fillStyle = 'rgba(0, 0, 0, 0.15)';
        perimeterCtx.fillRect(0, 0, perimeterCanvas.width, perimeterCanvas.height);
    } else {
        // Draw grid as fallback
        perimeterCtx.strokeStyle = '#333';
        perimeterCtx.lineWidth = 0.5;
        for (let x = 0; x < perimeterCanvas.width; x += 50) {
            perimeterCtx.beginPath();
            perimeterCtx.moveTo(x, 0);
            perimeterCtx.lineTo(x, perimeterCanvas.height);
            perimeterCtx.stroke();
        }
        for (let y = 0; y < perimeterCanvas.height; y += 50) {
            perimeterCtx.beginPath();
            perimeterCtx.moveTo(0, y);
            perimeterCtx.lineTo(perimeterCanvas.width, y);
            perimeterCtx.stroke();
        }
    }
    
    if (perimeterPoints.length === 0) {
        // Draw instruction overlay
        perimeterCtx.fillStyle = 'rgba(0, 0, 0, 0.6)';
        perimeterCtx.fillRect(perimeterCanvas.width/2 - 160, perimeterCanvas.height/2 - 30, 320, 60);
        perimeterCtx.fillStyle = '#fff';
        perimeterCtx.font = '16px sans-serif';
        perimeterCtx.textAlign = 'center';
        perimeterCtx.fillText('Click to add detection zone points', perimeterCanvas.width / 2, perimeterCanvas.height / 2);
        perimeterCtx.font = '12px sans-serif';
        perimeterCtx.fillStyle = '#aaa';
        perimeterCtx.fillText('Minimum 3 points required', perimeterCanvas.width / 2, perimeterCanvas.height / 2 + 20);
        return;
    }
    
    // Draw polygon
    if (perimeterPoints.length >= 2) {
        perimeterCtx.strokeStyle = '#58a6ff';
        perimeterCtx.lineWidth = 3;
        perimeterCtx.beginPath();
        perimeterCtx.moveTo(perimeterPoints[0][0], perimeterPoints[0][1]);
        
        for (let i = 1; i < perimeterPoints.length; i++) {
            perimeterCtx.lineTo(perimeterPoints[i][0], perimeterPoints[i][1]);
        }
        
        // Close polygon if 3+ points
        if (perimeterPoints.length >= 3) {
            perimeterCtx.closePath();
            perimeterCtx.fillStyle = 'rgba(88, 166, 255, 0.2)';
            perimeterCtx.fill();
        }
        
        perimeterCtx.stroke();
    }
    
    // Draw points with better visibility
    perimeterPoints.forEach((point, index) => {
        // Outer circle (white border)
        perimeterCtx.fillStyle = '#fff';
        perimeterCtx.beginPath();
        perimeterCtx.arc(point[0], point[1], 10, 0, Math.PI * 2);
        perimeterCtx.fill();
        
        // Inner circle (blue)
        perimeterCtx.fillStyle = '#58a6ff';
        perimeterCtx.beginPath();
        perimeterCtx.arc(point[0], point[1], 7, 0, Math.PI * 2);
        perimeterCtx.fill();
        
        // Draw point number
        perimeterCtx.fillStyle = '#fff';
        perimeterCtx.font = 'bold 11px sans-serif';
        perimeterCtx.textAlign = 'center';
        perimeterCtx.textBaseline = 'middle';
        perimeterCtx.fillText(String(index + 1), point[0], point[1]);
    });
}

function updatePointsCount() {
    document.getElementById('points-count').textContent = `Points: ${perimeterPoints.length}`;
}

async function savePerimeter() {
    if (perimeterPoints.length < 3) {
        alert('Please add at least 3 points to define a perimeter');
        return;
    }
    
    try {
        const response = await fetch('/api/perimeter', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ points: perimeterPoints })
        });
        
        if (response.ok) {
            alert('Perimeter saved successfully!');
        } else {
            alert('Failed to save perimeter');
        }
    } catch (error) {
        console.error('Error saving perimeter:', error);
        alert('Error saving perimeter');
    }
}

async function loadPerimeter() {
    try {
        const response = await fetch('/api/perimeter');
        const data = await response.json();
        
        if (data.points && data.points.length > 0) {
            perimeterPoints = data.points;
            drawPerimeter();
            updatePointsCount();
        }
    } catch (error) {
        console.error('Error loading perimeter:', error);
    }
}

// ============================================================================
// Calibration Editor
// ============================================================================
let calibrationPoints = [];
let calibrationCanvas, calibrationCtx;
let calibrationImage = null;
let isCalibrated = false;
let worldBounds = { min_x: 0, max_x: 10, min_y: 0, max_y: 10 };

function initCalibrationEditor() {
    calibrationCanvas = document.getElementById('calibration-canvas');
    if (!calibrationCanvas) return;
    
    calibrationCtx = calibrationCanvas.getContext('2d');
    
    // Handle canvas clicks
    calibrationCanvas.addEventListener('click', (e) => {
        if (calibrationPoints.length >= 4) {
            alert('Maximum 4 calibration points. Clear to start over.');
            return;
        }
        
        const rect = calibrationCanvas.getBoundingClientRect();
        const scaleX = calibrationCanvas.width / rect.width;
        const scaleY = calibrationCanvas.height / rect.height;
        
        const px = Math.round((e.clientX - rect.left) * scaleX);
        const py = Math.round((e.clientY - rect.top) * scaleY);
        
        // Prompt for world coordinates
        const worldX = prompt(`Point ${calibrationPoints.length + 1}: Enter X position in meters:`, '0');
        if (worldX === null) return;
        
        const worldY = prompt(`Point ${calibrationPoints.length + 1}: Enter Y position in meters:`, '0');
        if (worldY === null) return;
        
        calibrationPoints.push({
            pixel: [px, py],
            world: [parseFloat(worldX), parseFloat(worldY)]
        });
        
        drawCalibration();
        updateCalibrationUI();
    });
    
    // Clear button
    document.getElementById('clear-calibration').addEventListener('click', clearCalibration);
    
    // Save button
    document.getElementById('save-calibration').addEventListener('click', saveCalibration);
    
    // Refresh snapshot button
    const refreshBtn = document.getElementById('refresh-snapshot');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', captureCalibrationSnapshot);
    }
    
    // Initial snapshot capture
    captureCalibrationSnapshot();
}

function captureCalibrationSnapshot() {
    // Capture a snapshot from the video feed for calibration
    calibrationImage = new Image();
    calibrationImage.crossOrigin = 'anonymous';
    
    // Add timestamp to prevent caching
    const timestamp = new Date().getTime();
    calibrationImage.src = `/video_feed?snapshot=1&t=${timestamp}`;
    
    calibrationImage.onload = () => {
        drawCalibration();
    };
    
    calibrationImage.onerror = () => {
        console.log('Could not load camera snapshot, using placeholder');
        calibrationImage = null;
        drawCalibration();
    };
    
    // Also try to draw from video stream element as fallback
    setTimeout(() => {
        if (!calibrationImage || !calibrationImage.complete) {
            drawCalibrationFromVideoElement();
        }
    }, 500);
}

function drawCalibrationFromVideoElement() {
    // Try to capture from the video stream img element
    const videoStream = document.getElementById('video-stream');
    if (videoStream && videoStream.complete && videoStream.naturalWidth > 0) {
        // Create a temporary canvas to capture the video frame
        const tempCanvas = document.createElement('canvas');
        tempCanvas.width = calibrationCanvas.width;
        tempCanvas.height = calibrationCanvas.height;
        const tempCtx = tempCanvas.getContext('2d');
        
        try {
            tempCtx.drawImage(videoStream, 0, 0, calibrationCanvas.width, calibrationCanvas.height);
            calibrationImage = new Image();
            calibrationImage.src = tempCanvas.toDataURL();
            calibrationImage.onload = () => drawCalibration();
        } catch (e) {
            console.log('Could not capture video frame:', e);
        }
    }
}

function drawCalibration() {
    if (!calibrationCtx) return;
    
    // Clear canvas
    calibrationCtx.fillStyle = '#1a1a2e';
    calibrationCtx.fillRect(0, 0, calibrationCanvas.width, calibrationCanvas.height);
    
    // Draw camera snapshot as background if available
    if (calibrationImage && calibrationImage.complete && calibrationImage.naturalWidth > 0) {
        calibrationCtx.drawImage(calibrationImage, 0, 0, calibrationCanvas.width, calibrationCanvas.height);
        
        // Add semi-transparent overlay for better point visibility
        calibrationCtx.fillStyle = 'rgba(0, 0, 0, 0.2)';
        calibrationCtx.fillRect(0, 0, calibrationCanvas.width, calibrationCanvas.height);
    } else {
        // Draw grid as fallback
        calibrationCtx.strokeStyle = '#333';
        calibrationCtx.lineWidth = 0.5;
        for (let x = 0; x < calibrationCanvas.width; x += 50) {
            calibrationCtx.beginPath();
            calibrationCtx.moveTo(x, 0);
            calibrationCtx.lineTo(x, calibrationCanvas.height);
            calibrationCtx.stroke();
        }
        for (let y = 0; y < calibrationCanvas.height; y += 50) {
            calibrationCtx.beginPath();
            calibrationCtx.moveTo(0, y);
            calibrationCtx.lineTo(calibrationCanvas.width, y);
            calibrationCtx.stroke();
        }
    }
    
    if (calibrationPoints.length === 0) {
        // Draw instruction overlay
        calibrationCtx.fillStyle = 'rgba(0, 0, 0, 0.6)';
        calibrationCtx.fillRect(calibrationCanvas.width/2 - 180, calibrationCanvas.height/2 - 30, 360, 60);
        calibrationCtx.fillStyle = '#fff';
        calibrationCtx.font = '16px sans-serif';
        calibrationCtx.textAlign = 'center';
        calibrationCtx.fillText('Click on 4 markers in your yard', calibrationCanvas.width / 2, calibrationCanvas.height / 2);
        calibrationCtx.font = '12px sans-serif';
        calibrationCtx.fillStyle = '#aaa';
        calibrationCtx.fillText('Click "Refresh Snapshot" to update the image', calibrationCanvas.width / 2, calibrationCanvas.height / 2 + 20);
        return;
    }
    
    // Draw connecting lines if we have 4 points
    if (calibrationPoints.length >= 2) {
        calibrationCtx.strokeStyle = '#ff6b9d';
        calibrationCtx.lineWidth = 2;
        calibrationCtx.beginPath();
        calibrationCtx.moveTo(calibrationPoints[0].pixel[0], calibrationPoints[0].pixel[1]);
        for (let i = 1; i < calibrationPoints.length; i++) {
            calibrationCtx.lineTo(calibrationPoints[i].pixel[0], calibrationPoints[i].pixel[1]);
        }
        if (calibrationPoints.length === 4) {
            calibrationCtx.closePath();
        }
        calibrationCtx.stroke();
    }
    
    // Draw points
    calibrationPoints.forEach((point, index) => {
        const [px, py] = point.pixel;
        const [wx, wy] = point.world;
        
        // Draw point circle
        calibrationCtx.fillStyle = '#ff6b9d';
        calibrationCtx.beginPath();
        calibrationCtx.arc(px, py, 10, 0, Math.PI * 2);
        calibrationCtx.fill();
        
        // Draw point number
        calibrationCtx.fillStyle = '#fff';
        calibrationCtx.font = 'bold 14px sans-serif';
        calibrationCtx.textAlign = 'center';
        calibrationCtx.textBaseline = 'middle';
        calibrationCtx.fillText(String(index + 1), px, py);
        
        // Draw world coordinates label
        calibrationCtx.fillStyle = '#ff6b9d';
        calibrationCtx.font = '12px sans-serif';
        calibrationCtx.textAlign = 'left';
        calibrationCtx.fillText(`(${wx}m, ${wy}m)`, px + 15, py - 5);
    });
}

function updateCalibrationUI() {
    const pointsList = document.getElementById('calibration-points-list');
    const status = document.getElementById('calibration-status');
    
    // Update points list
    pointsList.innerHTML = calibrationPoints.map((p, i) => `
        <div class="calibration-point-item">
            <span class="point-number">${i + 1}</span>
            <span class="point-pixel">Pixel: (${p.pixel[0]}, ${p.pixel[1]})</span>
            <span class="point-world">World: (${p.world[0]}m, ${p.world[1]}m)</span>
        </div>
    `).join('');
    
    // Update status
    if (calibrationPoints.length < 4) {
        status.innerHTML = `<span class="status-icon">⚠️</span><span class="status-text">Add ${4 - calibrationPoints.length} more point(s)</span>`;
        status.className = 'calibration-status pending';
    } else {
        status.innerHTML = `<span class="status-icon">✓</span><span class="status-text">4 points ready - click Save</span>`;
        status.className = 'calibration-status ready';
    }
}

async function saveCalibration() {
    if (calibrationPoints.length !== 4) {
        alert('Please add exactly 4 calibration points');
        return;
    }
    
    try {
        const response = await fetch('/api/calibration', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ points: calibrationPoints })
        });
        
        if (response.ok) {
            const data = await response.json();
            isCalibrated = true;
            worldBounds = data.calibration.world_bounds;
            updateCalibrationBadge(true);
            alert('Calibration saved successfully!');
        } else {
            alert('Failed to save calibration');
        }
    } catch (error) {
        console.error('Error saving calibration:', error);
        alert('Error saving calibration');
    }
}

async function clearCalibration() {
    try {
        await fetch('/api/calibration', { method: 'DELETE' });
        calibrationPoints = [];
        isCalibrated = false;
        drawCalibration();
        updateCalibrationUI();
        updateCalibrationBadge(false);
    } catch (error) {
        console.error('Error clearing calibration:', error);
    }
}

async function loadCalibration() {
    try {
        const response = await fetch('/api/calibration');
        const data = await response.json();
        
        if (data.points && data.points.length === 4) {
            calibrationPoints = data.points;
            isCalibrated = data.is_calibrated;
            worldBounds = data.world_bounds;
            drawCalibration();
            updateCalibrationUI();
        }
        updateCalibrationBadge(isCalibrated);
    } catch (error) {
        console.error('Error loading calibration:', error);
    }
}

function updateCalibrationBadge(calibrated) {
    const badge = document.getElementById('calibration-badge');
    if (!badge) return;
    
    if (calibrated) {
        badge.textContent = '✓ Calibrated';
        badge.className = 'calibration-badge calibrated';
    } else {
        badge.textContent = '⚠️ Not Calibrated';
        badge.className = 'calibration-badge not-calibrated';
    }
}

// ============================================================================
// Mini Map
// ============================================================================
let minimapCanvas, minimapCtx;
let lastDetections = [];

function initMiniMap() {
    minimapCanvas = document.getElementById('minimap-canvas');
    if (!minimapCanvas) return;
    
    minimapCtx = minimapCanvas.getContext('2d');
    drawMiniMap();
}

function drawMiniMap() {
    if (!minimapCtx) return;
    
    const width = minimapCanvas.width;
    const height = minimapCanvas.height;
    
    // Clear canvas
    minimapCtx.fillStyle = '#1a1a2e';
    minimapCtx.fillRect(0, 0, width, height);
    
    // Draw grid
    const gridSpacing = 1; // 1 meter
    const worldWidth = worldBounds.max_x - worldBounds.min_x;
    const worldHeight = worldBounds.max_y - worldBounds.min_y;
    const scaleX = width / worldWidth;
    const scaleY = height / worldHeight;
    
    minimapCtx.strokeStyle = '#333';
    minimapCtx.lineWidth = 0.5;
    
    // Vertical grid lines
    for (let wx = Math.ceil(worldBounds.min_x); wx <= worldBounds.max_x; wx += gridSpacing) {
        const x = (wx - worldBounds.min_x) * scaleX;
        minimapCtx.beginPath();
        minimapCtx.moveTo(x, 0);
        minimapCtx.lineTo(x, height);
        minimapCtx.stroke();
        
        // Draw meter labels
        minimapCtx.fillStyle = '#666';
        minimapCtx.font = '10px sans-serif';
        minimapCtx.textAlign = 'center';
        minimapCtx.fillText(`${wx}m`, x, height - 5);
    }
    
    // Horizontal grid lines
    for (let wy = Math.ceil(worldBounds.min_y); wy <= worldBounds.max_y; wy += gridSpacing) {
        const y = height - (wy - worldBounds.min_y) * scaleY; // Flip Y axis
        minimapCtx.beginPath();
        minimapCtx.moveTo(0, y);
        minimapCtx.lineTo(width, y);
        minimapCtx.stroke();
        
        // Draw meter labels
        minimapCtx.fillStyle = '#666';
        minimapCtx.font = '10px sans-serif';
        minimapCtx.textAlign = 'left';
        minimapCtx.fillText(`${wy}m`, 5, y - 3);
    }
    
    // Draw origin marker
    const originX = (0 - worldBounds.min_x) * scaleX;
    const originY = height - (0 - worldBounds.min_y) * scaleY;
    minimapCtx.fillStyle = '#fff';
    minimapCtx.beginPath();
    minimapCtx.arc(originX, originY, 5, 0, Math.PI * 2);
    minimapCtx.fill();
    minimapCtx.fillText('(0,0)', originX + 8, originY + 4);
    
    // Draw calibration status
    if (!isCalibrated) {
        minimapCtx.fillStyle = 'rgba(255, 150, 50, 0.8)';
        minimapCtx.font = '14px sans-serif';
        minimapCtx.textAlign = 'center';
        minimapCtx.fillText('Not Calibrated', width / 2, height / 2);
        minimapCtx.font = '11px sans-serif';
        minimapCtx.fillText('Set up calibration in Control Panel', width / 2, height / 2 + 18);
        return;
    }
    
    // Draw detected objects
    lastDetections.forEach((det, index) => {
        if (!det.world_position) return;
        
        const wx = det.world_position.world_x;
        const wy = det.world_position.world_y;
        
        const x = (wx - worldBounds.min_x) * scaleX;
        const y = height - (wy - worldBounds.min_y) * scaleY; // Flip Y
        
        // Choose color based on class (17 = cat, 37 = ball)
        const isCat = det.class_id === 17;
        const color = isCat ? '#3fb950' : '#f0883e';
        
        // Draw object point
        minimapCtx.fillStyle = color;
        minimapCtx.beginPath();
        minimapCtx.arc(x, y, 8, 0, Math.PI * 2);
        minimapCtx.fill();
        
        // Draw border
        minimapCtx.strokeStyle = '#fff';
        minimapCtx.lineWidth = 2;
        minimapCtx.stroke();
        
        // Draw label
        minimapCtx.fillStyle = '#fff';
        minimapCtx.font = 'bold 10px sans-serif';
        minimapCtx.textAlign = 'center';
        minimapCtx.fillText(isCat ? '🐱' : '🏀', x, y + 4);
        
        // Draw coordinates
        minimapCtx.fillStyle = color;
        minimapCtx.font = '10px sans-serif';
        minimapCtx.fillText(`(${wx.toFixed(1)}, ${wy.toFixed(1)})`, x, y - 12);
    });
}

function updateObjectsList(detections) {
    const list = document.getElementById('objects-list');
    if (!list) return;
    
    if (!detections || detections.length === 0) {
        list.innerHTML = '<p class="no-objects">No objects detected</p>';
        return;
    }
    
    list.innerHTML = detections.map((det, i) => {
        const isCat = det.class_id === 17;
        const icon = isCat ? '🐱' : '🏀';
        const type = isCat ? 'Cat' : 'Ball';
        const conf = (det.confidence * 100).toFixed(0);
        
        let posText = 'Position: Not calibrated';
        if (det.world_position) {
            posText = `Position: (${det.world_position.world_x}m, ${det.world_position.world_y}m)`;
        }
        
        return `
            <div class="object-item ${isCat ? 'cat' : 'ball'}">
                <span class="object-icon">${icon}</span>
                <div class="object-info">
                    <span class="object-type">${type}</span>
                    <span class="object-conf">${conf}% confidence</span>
                    <span class="object-pos">${posText}</span>
                </div>
            </div>
        `;
    }).join('');
}

// ============================================================================
// Performance Controls
// ============================================================================
function initPerformanceControls() {
    const resolutionSelect = document.getElementById('resolution-select');
    const framerateSelect = document.getElementById('framerate-select');
    const frameskipSelect = document.getElementById('frameskip-select');
    
    resolutionSelect.addEventListener('change', async (e) => {
        const [width, height] = e.target.value.split(',').map(Number);
        await setResolution(width, height);
    });
    
    framerateSelect.addEventListener('change', async (e) => {
        const fps = parseInt(e.target.value);
        await setFramerate(fps);
    });
    
    frameskipSelect.addEventListener('change', async (e) => {
        const skip = parseInt(e.target.value);
        await setFrameskip(skip);
    });
}

async function setResolution(width, height) {
    updatePerfStatus('applying', 'Changing resolution...');
    try {
        const response = await fetch('/api/performance/resolution', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ width, height })
        });
        
        if (response.ok) {
            updatePerfStatus('success', `Resolution set to ${width}×${height}`);
            // Refresh video feed
            refreshVideoFeed();
        } else {
            updatePerfStatus('error', 'Failed to change resolution');
        }
    } catch (error) {
        console.error('Error setting resolution:', error);
        updatePerfStatus('error', 'Error changing resolution');
    }
}

async function setFramerate(fps) {
    updatePerfStatus('applying', 'Changing frame rate...');
    try {
        const response = await fetch('/api/performance/framerate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fps })
        });
        
        if (response.ok) {
            updatePerfStatus('success', `Frame rate set to ${fps} FPS`);
            refreshVideoFeed();
        } else {
            updatePerfStatus('error', 'Failed to change frame rate');
        }
    } catch (error) {
        console.error('Error setting framerate:', error);
        updatePerfStatus('error', 'Error changing frame rate');
    }
}

async function setFrameskip(skip) {
    updatePerfStatus('applying', 'Changing frame skip...');
    try {
        const response = await fetch('/api/performance/frameskip', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ skip })
        });
        
        if (response.ok) {
            updatePerfStatus('success', `Frame skip set to ${skip}`);
        } else {
            updatePerfStatus('error', 'Failed to change frame skip');
        }
    } catch (error) {
        console.error('Error setting frameskip:', error);
        updatePerfStatus('error', 'Error changing frame skip');
    }
}

function updatePerfStatus(state, message) {
    const indicator = document.getElementById('perf-indicator');
    const text = document.getElementById('perf-status-text');
    
    text.textContent = message;
    
    indicator.className = 'perf-indicator';
    if (state === 'applying') {
        indicator.classList.add('applying');
    } else if (state === 'success') {
        indicator.classList.add('success');
        setTimeout(() => {
            indicator.classList.remove('success');
            text.textContent = 'Settings loaded';
        }, 3000);
    } else if (state === 'error') {
        indicator.classList.add('error');
    }
}

function refreshVideoFeed() {
    // Force refresh the video stream by adding timestamp
    const videoStream = document.getElementById('video-stream');
    const timestamp = new Date().getTime();
    videoStream.src = `/video_feed?t=${timestamp}`;
}

async function loadPerformanceSettings() {
    try {
        const response = await fetch('/api/performance');
        const data = await response.json();
        
        // Update select elements to match current settings
        const resolutionSelect = document.getElementById('resolution-select');
        const framerateSelect = document.getElementById('framerate-select');
        const frameskipSelect = document.getElementById('frameskip-select');
        
        const currentRes = data.current.resolution.join(',');
        resolutionSelect.value = currentRes;
        
        framerateSelect.value = data.current.framerate;
        frameskipSelect.value = data.current.frame_skip;
        
    } catch (error) {
        console.error('Error loading performance settings:', error);
    }
}

// ============================================================================
// Status Updates
// ============================================================================
function initStatusUpdates() {
    // Update status every second
    setInterval(updateStatus, 1000);
}

async function updateStatus() {
    try {
        const response = await fetch('/api/status');
        const status = await response.json();
        
        // Update video overlay
        document.getElementById('fps-display').textContent = `FPS: ${status.fps}`;
        
        // Update status grid
        document.getElementById('status-fps').textContent = status.fps;
        document.getElementById('status-objects').textContent = status.object_count;
        document.getElementById('status-frames').textContent = formatNumber(status.frame_count);
        document.getElementById('status-perimeter').textContent = status.perimeter_points;
        
        // Update performance status
        if (status.resolution) {
            document.getElementById('status-resolution').textContent = 
                `${status.resolution[0]}×${status.resolution[1]}`;
        }
        if (status.frame_skip) {
            document.getElementById('status-frameskip').textContent = status.frame_skip;
        }
        
        // Update RAM usage
        const ramEl = document.getElementById('status-ram');
        if (ramEl && status.ram_used_mb !== null) {
            ramEl.textContent = `${status.ram_used_mb}/${status.ram_total_mb}MB`;
            // Color code: green < 70%, yellow 70-85%, red > 85%
            if (status.ram_percent > 85) {
                ramEl.style.color = '#ff6b6b';
            } else if (status.ram_percent > 70) {
                ramEl.style.color = '#ffd93d';
            } else {
                ramEl.style.color = '#6bcf6b';
            }
        }
        
        // Update CPU temperature
        const tempEl = document.getElementById('status-temp');
        if (tempEl && status.cpu_temp !== null) {
            tempEl.textContent = `${status.cpu_temp}°C`;
            // Color code: green < 60°C, yellow 60-75°C, red > 75°C
            if (status.cpu_temp > 75) {
                tempEl.style.color = '#ff6b6b';
            } else if (status.cpu_temp > 60) {
                tempEl.style.color = '#ffd93d';
            } else {
                tempEl.style.color = '#6bcf6b';
            }
        }
        
        // Update calibration status
        isCalibrated = status.is_calibrated;
        updateCalibrationBadge(isCalibrated);
        
        // Update mini-map and objects list with detections
        if (status.detections) {
            lastDetections = status.detections;
            drawMiniMap();
            updateObjectsList(status.detections);
        }
        
    } catch (error) {
        console.error('Error fetching status:', error);
    }
}

function formatNumber(num) {
    if (num >= 1000000) {
        return (num / 1000000).toFixed(1) + 'M';
    }
    if (num >= 1000) {
        return (num / 1000).toFixed(1) + 'K';
    }
    return String(num);
}

// ============================================================================
// Initial State Loading
// ============================================================================
async function loadCurrentState() {
    try {
        // Load current mode
        const modeResponse = await fetch('/api/mode');
        const modeData = await modeResponse.json();
        updateModeUI(modeData.mode);
        
        // Load perimeter
        await loadPerimeter();
        
        // Load calibration
        await loadCalibration();
        
        // Load performance settings
        await loadPerformanceSettings();
        
        // Initial status update
        await updateStatus();
        
        // Initial mini-map draw
        drawMiniMap();
        
    } catch (error) {
        console.error('Error loading initial state:', error);
    }
}
