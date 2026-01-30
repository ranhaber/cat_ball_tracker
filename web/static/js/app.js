/**
 * Cat Dome - Frontend JavaScript
 * Handles tab switching, mode toggle, perimeter drawing, and status updates
 * With auto-reconnect on connection loss
 */

// ============================================================================
// Tab Navigation
// ============================================================================
document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    initModeToggle();
    initPerimeterEditor();
    initStatusUpdates();
    initVideoReconnect();
    initResolutionSelector();
    initMotionControls();
    initCalibration();
    loadCurrentState();
});

function initTabs() {
    const tabButtons = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    
    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            tabButtons.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            const tabId = btn.dataset.tab + '-tab';
            document.getElementById(tabId).classList.add('active');
        });
    });
}

// ============================================================================
// Video Stream with Auto-Reconnect
// ============================================================================
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 100;
const RECONNECT_DELAY = 3000; // 3 seconds

function initVideoReconnect() {
    const videoStream = document.getElementById('video-stream');
    
    videoStream.onerror = () => {
        console.log('Video stream error - attempting reconnect...');
        showConnectionStatus('disconnected');
        scheduleReconnect();
    };
    
    // Periodic check if stream is stale
    setInterval(checkVideoHealth, 5000);
}

function scheduleReconnect() {
    if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
        showConnectionStatus('failed');
        return;
    }
    
    reconnectAttempts++;
    console.log(`Reconnect attempt ${reconnectAttempts}...`);
    
    setTimeout(() => {
        reconnectVideo();
    }, RECONNECT_DELAY);
}

function reconnectVideo() {
    const videoStream = document.getElementById('video-stream');
    const timestamp = new Date().getTime();
    
    // Add timestamp to force reload
    videoStream.src = `/video_feed?t=${timestamp}`;
    
    showConnectionStatus('connecting');
    
    // Check if reconnect was successful
    setTimeout(() => {
        if (videoStream.complete && videoStream.naturalWidth > 0) {
            reconnectAttempts = 0;
            showConnectionStatus('connected');
        }
    }, 2000);
}

function checkVideoHealth() {
    const videoStream = document.getElementById('video-stream');
    
    // If image seems broken, try reconnect
    if (!videoStream.complete || videoStream.naturalWidth === 0) {
        if (reconnectAttempts === 0) {
            scheduleReconnect();
        }
    } else {
        showConnectionStatus('connected');
    }
}

function showConnectionStatus(status) {
    let statusEl = document.getElementById('connection-status');
    if (!statusEl) {
        statusEl = document.createElement('div');
        statusEl.id = 'connection-status';
        statusEl.style.cssText = 'position:fixed;top:10px;left:50%;transform:translateX(-50%);padding:10px 20px;border-radius:8px;font-weight:bold;z-index:1000;';
        document.body.appendChild(statusEl);
    }
    
    switch(status) {
        case 'connected':
            statusEl.style.display = 'none';
            break;
        case 'connecting':
            statusEl.style.display = 'block';
            statusEl.style.background = '#d29922';
            statusEl.textContent = `🔄 Reconnecting... (${reconnectAttempts})`;
            break;
        case 'disconnected':
            statusEl.style.display = 'block';
            statusEl.style.background = '#f85149';
            statusEl.textContent = '❌ Connection lost';
            break;
        case 'failed':
            statusEl.style.display = 'block';
            statusEl.style.background = '#f85149';
            statusEl.textContent = '❌ Failed to reconnect - refresh page';
            break;
    }
}

// ============================================================================
// Resolution Selector
// ============================================================================
function initResolutionSelector() {
    const selector = document.getElementById('resolution-select');
    if (selector) {
        selector.addEventListener('change', (e) => {
            setResolution(e.target.value);
        });
    }
}

async function setResolution(resolutionStr) {
    try {
        // Parse "640x480" into width and height
        const [width, height] = resolutionStr.split('x').map(Number);
        
        showConnectionStatus('connecting');
        
        const response = await fetch('/api/performance/resolution', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ width, height })
        });
        
        if (response.ok) {
            console.log(`Resolution changed to ${width}x${height}`);
            // Wait for camera to restart, then reconnect video
            setTimeout(reconnectVideo, 2000);
        } else {
            const err = await response.json();
            alert('Failed to change resolution: ' + (err.error || 'Unknown error'));
        }
    } catch (error) {
        console.error('Error setting resolution:', error);
        alert('Error setting resolution: ' + error.message);
    }
}

async function loadResolution() {
    try {
        const response = await fetch('/api/performance');
        const data = await response.json();
        const selector = document.getElementById('resolution-select');
        
        if (selector && data.current && data.current.resolution) {
            const [width, height] = data.current.resolution;
            selector.value = `${width}x${height}`;
        }
    } catch (error) {
        console.error('Error loading resolution:', error);
    }
}

// ============================================================================
// Motion & Performance Controls
// ============================================================================
function initMotionControls() {
    // Show motion regions checkbox (in video tab)
    const showMotionCheckbox = document.getElementById('show-motion-checkbox');
    if (showMotionCheckbox) {
        showMotionCheckbox.addEventListener('change', async (e) => {
            try {
                await fetch('/api/motion/show_regions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ show: e.target.checked })
                });
            } catch (error) {
                console.error('Error toggling show regions:', error);
            }
        });
    }
    
    // Frame skip selector
    const frameskipSelect = document.getElementById('frameskip-select');
    if (frameskipSelect) {
        frameskipSelect.addEventListener('change', async (e) => {
            const skip = parseInt(e.target.value);
            try {
                const response = await fetch('/api/performance/frameskip', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ skip })
                });
                if (response.ok) {
                    console.log(`Frame skip changed to ${skip}`);
                }
            } catch (error) {
                console.error('Error setting frame skip:', error);
            }
        });
    }
}

async function loadMotionSettings() {
    try {
        const response = await fetch('/api/motion');
        const data = await response.json();
        
        // Update checkbox
        const showMotionCheckbox = document.getElementById('show-motion-checkbox');
        if (showMotionCheckbox) {
            showMotionCheckbox.checked = data.show_motion_regions || false;
        }
    } catch (error) {
        console.error('Error loading motion settings:', error);
    }
    
    // Load frame skip
    try {
        const response = await fetch('/api/performance');
        const data = await response.json();
        const frameskipSelect = document.getElementById('frameskip-select');
        if (frameskipSelect && data.current && data.current.frame_skip) {
            frameskipSelect.value = data.current.frame_skip;
        }
    } catch (error) {
        console.error('Error loading frame skip:', error);
    }
}

// ============================================================================
// Calibration Controls
// ============================================================================
let calibrationCanvas, calibrationCtx;
let calibrationImage = null;
let calibrationLines = [];  // Array of { p1: [x,y], p2: [x,y], distance: number }
let calibrationTempPoint = null;  // First point of current line being drawn

function initCalibration() {
    calibrationCanvas = document.getElementById('calibration-canvas');
    if (!calibrationCanvas) return;
    
    calibrationCtx = calibrationCanvas.getContext('2d');
    
    // Load snapshot button
    document.getElementById('load-snapshot-calibration')?.addEventListener('click', loadCalibrationSnapshot);
    
    // Clear button
    document.getElementById('clear-calibration')?.addEventListener('click', clearCalibration);
    
    // Canvas click handler
    calibrationCanvas.addEventListener('click', handleCalibrationClick);
    
    // Load saved calibration
    loadCalibrationStatus();
}

async function loadCalibrationSnapshot() {
    const btn = document.getElementById('load-snapshot-calibration');
    if (btn) btn.textContent = '⏳ Loading...';
    
    try {
        const response = await fetch('/video_feed?snapshot=1');
        const blob = await response.blob();
        
        calibrationImage = new Image();
        calibrationImage.onload = () => {
            // Resize canvas to match image aspect ratio
            const aspectRatio = calibrationImage.width / calibrationImage.height;
            calibrationCanvas.width = 640;
            calibrationCanvas.height = Math.round(640 / aspectRatio);
            
            // Mark container as having image
            calibrationCanvas.parentElement.classList.add('has-image');
            
            drawCalibration();
            if (btn) btn.textContent = '📷 Refresh Frame';
        };
        calibrationImage.src = URL.createObjectURL(blob);
    } catch (error) {
        console.error('Error loading snapshot:', error);
        alert('Failed to load camera frame');
        if (btn) btn.textContent = '📷 Load Camera Frame';
    }
}

function handleCalibrationClick(e) {
    if (!calibrationImage) {
        alert('Please load a camera frame first');
        return;
    }
    
    const rect = calibrationCanvas.getBoundingClientRect();
    const scaleX = calibrationCanvas.width / rect.width;
    const scaleY = calibrationCanvas.height / rect.height;
    
    const x = Math.round((e.clientX - rect.left) * scaleX);
    const y = Math.round((e.clientY - rect.top) * scaleY);
    
    if (calibrationTempPoint === null) {
        // First point of a line
        calibrationTempPoint = [x, y];
        drawCalibration();
    } else {
        // Second point - complete the line
        const p1 = calibrationTempPoint;
        const p2 = [x, y];
        calibrationTempPoint = null;
        
        // Ask for distance
        const distance = prompt('Enter the distance between these two points (in meters):');
        if (distance && !isNaN(parseFloat(distance))) {
            calibrationLines.push({
                p1: p1,
                p2: p2,
                distance: parseFloat(distance)
            });
            updateCalibrationLinesCount();
            saveCalibrationToServer();
        }
        
        drawCalibration();
    }
}

function drawCalibration() {
    if (!calibrationCtx) return;
    
    // Draw background image or black
    if (calibrationImage) {
        calibrationCtx.drawImage(calibrationImage, 0, 0, calibrationCanvas.width, calibrationCanvas.height);
    } else {
        calibrationCtx.fillStyle = '#000';
        calibrationCtx.fillRect(0, 0, calibrationCanvas.width, calibrationCanvas.height);
    }
    
    // Draw existing lines
    calibrationLines.forEach((line, index) => {
        drawCalibrationLine(line.p1, line.p2, line.distance, index + 1);
    });
    
    // Draw temp point if exists
    if (calibrationTempPoint) {
        calibrationCtx.fillStyle = '#ffff00';
        calibrationCtx.beginPath();
        calibrationCtx.arc(calibrationTempPoint[0], calibrationTempPoint[1], 8, 0, Math.PI * 2);
        calibrationCtx.fill();
        
        calibrationCtx.fillStyle = '#000';
        calibrationCtx.font = 'bold 12px sans-serif';
        calibrationCtx.textAlign = 'center';
        calibrationCtx.fillText('Click 2nd point', calibrationTempPoint[0], calibrationTempPoint[1] - 15);
    }
}

function drawCalibrationLine(p1, p2, distance, lineNum) {
    // Draw line
    calibrationCtx.strokeStyle = '#ff00ff';
    calibrationCtx.lineWidth = 3;
    calibrationCtx.beginPath();
    calibrationCtx.moveTo(p1[0], p1[1]);
    calibrationCtx.lineTo(p2[0], p2[1]);
    calibrationCtx.stroke();
    
    // Draw endpoints
    [p1, p2].forEach(point => {
        calibrationCtx.fillStyle = '#ff00ff';
        calibrationCtx.beginPath();
        calibrationCtx.arc(point[0], point[1], 6, 0, Math.PI * 2);
        calibrationCtx.fill();
    });
    
    // Draw distance label at midpoint
    const midX = (p1[0] + p2[0]) / 2;
    const midY = (p1[1] + p2[1]) / 2;
    
    const label = `${distance}m`;
    calibrationCtx.font = 'bold 14px sans-serif';
    calibrationCtx.textAlign = 'center';
    
    // Background for label
    const metrics = calibrationCtx.measureText(label);
    calibrationCtx.fillStyle = 'rgba(0,0,0,0.7)';
    calibrationCtx.fillRect(midX - metrics.width/2 - 5, midY - 10, metrics.width + 10, 20);
    
    calibrationCtx.fillStyle = '#fff';
    calibrationCtx.fillText(label, midX, midY + 5);
}

function updateCalibrationLinesCount() {
    const el = document.getElementById('calibration-lines');
    if (el) {
        el.textContent = `Lines defined: ${calibrationLines.length}`;
    }
}

async function loadCalibrationStatus() {
    try {
        const response = await fetch('/api/calibration');
        const data = await response.json();
        
        // Load saved lines if any
        if (data.lines && Array.isArray(data.lines)) {
            calibrationLines = data.lines;
            updateCalibrationLinesCount();
        }
        
        updateCalibrationStatusUI(data);
    } catch (error) {
        console.error('Error loading calibration:', error);
    }
}

function updateCalibrationStatusUI(data) {
    const statusEl = document.getElementById('calibration-status');
    if (statusEl) {
        if (data.is_calibrated || calibrationLines.length > 0) {
            statusEl.textContent = `Calibrated (${calibrationLines.length} line${calibrationLines.length !== 1 ? 's' : ''})`;
            statusEl.style.color = '#3fb950';
        } else {
            statusEl.textContent = 'Not calibrated';
            statusEl.style.color = '#d29922';
        }
    }
}

async function saveCalibrationToServer() {
    try {
        const response = await fetch('/api/calibration/lines', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lines: calibrationLines })
        });
        if (response.ok) {
            const data = await response.json();
            updateCalibrationStatusUI(data);
            console.log('Calibration saved');
        }
    } catch (error) {
        console.error('Error saving calibration:', error);
    }
}

async function clearCalibration() {
    calibrationLines = [];
    calibrationTempPoint = null;
    updateCalibrationLinesCount();
    drawCalibration();
    
    try {
        const response = await fetch('/api/calibration', {
            method: 'DELETE'
        });
        if (response.ok) {
            const data = await response.json();
            updateCalibrationStatusUI(data.calibration || {});
            console.log('Calibration cleared');
        }
    } catch (error) {
        console.error('Error clearing calibration:', error);
    }
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
    if (modeDisplay) modeDisplay.textContent = `Mode: ${modeLabel}`;
    if (currentMode) currentMode.textContent = modeLabel;
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
    
    // Load snapshot button
    document.getElementById('load-snapshot-perimeter')?.addEventListener('click', loadPerimeterSnapshot);
    
    // Canvas click handler
    perimeterCanvas.addEventListener('click', (e) => {
        if (!perimeterImage) {
            alert('Please load a camera frame first');
            return;
        }
        
        const rect = perimeterCanvas.getBoundingClientRect();
        const scaleX = perimeterCanvas.width / rect.width;
        const scaleY = perimeterCanvas.height / rect.height;
        
        const x = Math.round((e.clientX - rect.left) * scaleX);
        const y = Math.round((e.clientY - rect.top) * scaleY);
        
        perimeterPoints.push([x, y]);
        drawPerimeter();
        updatePointsCount();
    });
    
    document.getElementById('clear-perimeter')?.addEventListener('click', () => {
        perimeterPoints = [];
        drawPerimeter();
        updatePointsCount();
    });
    
    document.getElementById('save-perimeter')?.addEventListener('click', savePerimeter);
}

async function loadPerimeterSnapshot() {
    const btn = document.getElementById('load-snapshot-perimeter');
    if (btn) btn.textContent = '⏳ Loading...';
    
    try {
        const response = await fetch('/video_feed?snapshot=1');
        const blob = await response.blob();
        
        perimeterImage = new Image();
        perimeterImage.onload = () => {
            // Resize canvas to match image aspect ratio
            const aspectRatio = perimeterImage.width / perimeterImage.height;
            perimeterCanvas.width = 640;
            perimeterCanvas.height = Math.round(640 / aspectRatio);
            
            // Mark container as having image
            perimeterCanvas.parentElement.classList.add('has-image');
            
            drawPerimeter();
            if (btn) btn.textContent = '📷 Refresh Frame';
        };
        perimeterImage.src = URL.createObjectURL(blob);
    } catch (error) {
        console.error('Error loading snapshot:', error);
        alert('Failed to load camera frame');
        if (btn) btn.textContent = '📷 Load Camera Frame';
    }
}

function drawPerimeter() {
    if (!perimeterCtx) return;
    
    // Draw background image or black
    if (perimeterImage) {
        perimeterCtx.drawImage(perimeterImage, 0, 0, perimeterCanvas.width, perimeterCanvas.height);
    } else {
        perimeterCtx.fillStyle = '#000';
        perimeterCtx.fillRect(0, 0, perimeterCanvas.width, perimeterCanvas.height);
    }
    
    if (perimeterPoints.length === 0) {
        return;
    }
    
    // Draw polygon
    if (perimeterPoints.length >= 2) {
        perimeterCtx.strokeStyle = '#00ff00';
        perimeterCtx.lineWidth = 3;
        perimeterCtx.beginPath();
        perimeterCtx.moveTo(perimeterPoints[0][0], perimeterPoints[0][1]);
        
        for (let i = 1; i < perimeterPoints.length; i++) {
            perimeterCtx.lineTo(perimeterPoints[i][0], perimeterPoints[i][1]);
        }
        
        if (perimeterPoints.length >= 3) {
            perimeterCtx.closePath();
            perimeterCtx.fillStyle = 'rgba(0, 255, 0, 0.2)';
            perimeterCtx.fill();
        }
        
        perimeterCtx.stroke();
    }
    
    // Draw points
    perimeterPoints.forEach((point, index) => {
        // Outer circle
        perimeterCtx.fillStyle = '#00ff00';
        perimeterCtx.beginPath();
        perimeterCtx.arc(point[0], point[1], 8, 0, Math.PI * 2);
        perimeterCtx.fill();
        
        // Inner circle
        perimeterCtx.fillStyle = '#000';
        perimeterCtx.beginPath();
        perimeterCtx.arc(point[0], point[1], 4, 0, Math.PI * 2);
        perimeterCtx.fill();
        
        // Label
        perimeterCtx.fillStyle = '#fff';
        perimeterCtx.font = 'bold 14px sans-serif';
        perimeterCtx.textAlign = 'center';
        perimeterCtx.strokeStyle = '#000';
        perimeterCtx.lineWidth = 3;
        perimeterCtx.strokeText(String(index + 1), point[0], point[1] - 15);
        perimeterCtx.fillText(String(index + 1), point[0], point[1] - 15);
    });
}

function updatePointsCount() {
    const el = document.getElementById('points-count');
    if (el) el.textContent = `Points: ${perimeterPoints.length}`;
}

async function savePerimeter() {
    if (perimeterPoints.length < 3) {
        alert('Please add at least 3 points');
        return;
    }
    
    try {
        const response = await fetch('/api/perimeter', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ points: perimeterPoints })
        });
        
        if (response.ok) {
            alert('Perimeter saved!');
        }
    } catch (error) {
        console.error('Error saving perimeter:', error);
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
// Status Updates
// ============================================================================
function initStatusUpdates() {
    setInterval(updateStatus, 1000);
}

async function updateStatus() {
    try {
        const response = await fetch('/api/status');
        const status = await response.json();
        
        const fpsDisplay = document.getElementById('fps-display');
        if (fpsDisplay) fpsDisplay.textContent = `FPS: ${status.fps}`;
        
        // Update overlay RAM display
        const ramDisplay = document.getElementById('ram-display');
        if (ramDisplay && status.ram_percent !== null) {
            ramDisplay.textContent = `RAM: ${status.ram_percent}%`;
        }
        
        // Update overlay temp display
        const tempDisplay = document.getElementById('temp-display');
        if (tempDisplay && status.cpu_temp !== null) {
            tempDisplay.textContent = `Temp: ${status.cpu_temp}°C`;
        }
        
        const statusFps = document.getElementById('status-fps');
        if (statusFps) statusFps.textContent = status.fps;
        
        const statusObjects = document.getElementById('status-objects');
        if (statusObjects) statusObjects.textContent = status.object_count;
        
        const statusFrames = document.getElementById('status-frames');
        if (statusFrames) statusFrames.textContent = formatNumber(status.frame_count);
        
        const statusPerimeter = document.getElementById('status-perimeter');
        if (statusPerimeter) statusPerimeter.textContent = status.perimeter_points;
        
        const statusResolution = document.getElementById('status-resolution');
        if (statusResolution) {
            if (status.resolution && Array.isArray(status.resolution)) {
                statusResolution.textContent = `${status.resolution[0]}x${status.resolution[1]}`;
            } else {
                statusResolution.textContent = status.resolution || '--';
            }
        }
        
        // Update motion detection status
        const motionStatus = document.getElementById('motion-status');
        if (motionStatus) {
            motionStatus.textContent = status.motion_detected ? 'ACTIVE' : 'Idle';
            motionStatus.style.color = status.motion_detected ? '#ffd700' : '#888';
        }
        
        const aiRuns = document.getElementById('ai-runs');
        if (aiRuns) {
            aiRuns.textContent = formatNumber(status.ai_detections_count || 0);
        }
        
        // Update show motion checkbox
        const showMotionCheckbox = document.getElementById('show-motion-checkbox');
        if (showMotionCheckbox && status.show_motion_regions !== undefined) {
            showMotionCheckbox.checked = status.show_motion_regions;
        }
        
        // Update RAM usage
        const statusRam = document.getElementById('status-ram');
        if (statusRam && status.ram_used_mb !== null) {
            const ramPercent = status.ram_percent || 0;
            statusRam.textContent = `${status.ram_used_mb}/${status.ram_total_mb}MB (${ramPercent}%)`;
            // Color code based on usage
            if (ramPercent > 85) {
                statusRam.style.color = '#ff4444';  // Red - critical
            } else if (ramPercent > 70) {
                statusRam.style.color = '#ffaa00';  // Orange - warning
            } else {
                statusRam.style.color = '#44ff44';  // Green - good
            }
        }
        
        // Update CPU temperature
        const statusTemp = document.getElementById('status-temp');
        if (statusTemp && status.cpu_temp !== null) {
            statusTemp.textContent = `${status.cpu_temp}°C`;
            // Color code based on temperature
            if (status.cpu_temp > 70) {
                statusTemp.style.color = '#ff4444';  // Red - hot
            } else if (status.cpu_temp > 55) {
                statusTemp.style.color = '#ffaa00';  // Orange - warm
            } else {
                statusTemp.style.color = '#44ff44';  // Green - cool
            }
        }
        
    } catch (error) {
        console.error('Error fetching status:', error);
    }
}

function formatNumber(num) {
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
    return String(num);
}

// ============================================================================
// Initial State Loading
// ============================================================================
async function loadCurrentState() {
    try {
        const modeResponse = await fetch('/api/mode');
        const modeData = await modeResponse.json();
        updateModeUI(modeData.mode);
        
        await loadPerimeter();
        await loadResolution();
        await loadMotionSettings();
        await loadCalibrationStatus();
        await updateStatus();
        
    } catch (error) {
        console.error('Error loading initial state:', error);
    }
}
