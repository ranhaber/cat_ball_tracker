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
    initTopDownView();
    initThresholdSlider();
    initConfirmSlider();
    initProfileSelector();
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

// ============================================================================
// Threshold Slider
// ============================================================================
function initThresholdSlider() {
    const slider = document.getElementById('threshold-slider');
    const valueDisplay = document.getElementById('threshold-value');
    
    if (slider) {
        // Update display when slider moves
        slider.addEventListener('input', (e) => {
            valueDisplay.textContent = e.target.value + '%';
        });
        
        // Save when slider is released
        slider.addEventListener('change', async (e) => {
            const threshold = parseInt(e.target.value) / 100;
            try {
                const response = await fetch('/api/performance/threshold', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ threshold })
                });
                if (response.ok) {
                    console.log(`Threshold set to ${threshold}`);
                }
            } catch (error) {
                console.error('Error setting threshold:', error);
            }
        });
    }
}

async function loadThreshold() {
    try {
        const response = await fetch('/api/performance/threshold');
        const data = await response.json();
        
        if (data.threshold !== undefined) {
            const slider = document.getElementById('threshold-slider');
            const valueDisplay = document.getElementById('threshold-value');
            const percent = Math.round(data.threshold * 100);
            
            if (slider) slider.value = percent;
            if (valueDisplay) valueDisplay.textContent = percent + '%';
        }
    } catch (error) {
        console.error('Error loading threshold:', error);
    }
}

// ============================================================================
// Confirmation Frames Slider (Temporal Confirmation)
// ============================================================================
function initConfirmSlider() {
    const slider = document.getElementById('confirm-slider');
    const valueDisplay = document.getElementById('confirm-value');
    
    if (slider) {
        // Update display when slider moves
        slider.addEventListener('input', (e) => {
            valueDisplay.textContent = e.target.value;
        });
        
        // Save when slider is released
        slider.addEventListener('change', async (e) => {
            const frames = parseInt(e.target.value);
            try {
                const response = await fetch('/api/performance/confirm_frames', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ frames })
                });
                if (response.ok) {
                    console.log(`Confirmation frames set to ${frames}`);
                }
            } catch (error) {
                console.error('Error setting confirmation frames:', error);
            }
        });
    }
}

// ============================================================================
// Performance Profile Selector (Phase 2)
// ============================================================================
function initProfileSelector() {
    const profileRadios = document.querySelectorAll('input[name="profile"]');
    
    profileRadios.forEach(radio => {
        radio.addEventListener('change', async (e) => {
            const profile = e.target.value;
            console.log(`Switching to profile: ${profile}`);
            
            try {
                const response = await fetch('/api/performance/profile', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ profile })
                });
                
                if (response.ok) {
                    const data = await response.json();
                    console.log(`Profile changed to: ${data.profile}`, data.settings);
                    
                    // Show brief success indicator
                    showNotification(`✅ Switched to ${data.settings.name} profile`, 'success');
                } else {
                    console.error('Failed to change profile');
                    showNotification('❌ Failed to change profile', 'error');
                    // Revert radio selection
                    await loadCurrentProfile();
                }
            } catch (error) {
                console.error('Error changing profile:', error);
                showNotification('❌ Error changing profile', 'error');
                // Revert radio selection
                await loadCurrentProfile();
            }
        });
    });
    
    // Load current profile on startup
    loadCurrentProfile();
}

async function loadCurrentProfile() {
    try {
        const response = await fetch('/api/performance/profile');
        if (response.ok) {
            const data = await response.json();
            const profileName = data.profile;
            
            // Update radio button selection
            const radio = document.querySelector(`input[name="profile"][value="${profileName}"]`);
            if (radio) {
                radio.checked = true;
            }
            
            console.log(`Current profile: ${profileName}`);
        }
    } catch (error) {
        console.error('Error loading current profile:', error);
    }
}

function showNotification(message, type = 'info') {
    // Simple notification - could be enhanced with a toast library
    const notificationArea = document.createElement('div');
    notificationArea.className = `notification notification-${type}`;
    notificationArea.textContent = message;
    notificationArea.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: ${type === 'success' ? '#3fb950' : '#f85149'};
        color: white;
        padding: 15px 25px;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        z-index: 10000;
        font-weight: 500;
        animation: slideIn 0.3s ease;
    `;
    
    document.body.appendChild(notificationArea);
    
    setTimeout(() => {
        notificationArea.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => {
            notificationArea.remove();
        }, 300);
    }, 3000);
}

// Add animations to style
if (!document.getElementById('notification-styles')) {
    const style = document.createElement('style');
    style.id = 'notification-styles';
    style.textContent = `
        @keyframes slideIn {
            from { transform: translateX(400px); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
        @keyframes slideOut {
            from { transform: translateX(0); opacity: 1; }
            to { transform: translateX(400px); opacity: 0; }
        }
    `;
    document.head.appendChild(style);
}

async function loadConfirmFrames() {
    try {
        const response = await fetch('/api/performance/confirm_frames');
        const data = await response.json();
        
        if (data.confirm_frames !== undefined) {
            const slider = document.getElementById('confirm-slider');
            const valueDisplay = document.getElementById('confirm-value');
            
            if (slider) slider.value = data.confirm_frames;
            if (valueDisplay) valueDisplay.textContent = data.confirm_frames;
        }
    } catch (error) {
        console.error('Error loading confirmation frames:', error);
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
let calibrationPoints = [];  // Array of { pixel: [x,y], world: [x,y] }

function initCalibration() {
    calibrationCanvas = document.getElementById('calibration-canvas');
    if (!calibrationCanvas) return;
    
    calibrationCtx = calibrationCanvas.getContext('2d');
    
    // Load snapshot button
    document.getElementById('load-snapshot-calibration')?.addEventListener('click', loadCalibrationSnapshot);
    
    // Save button
    document.getElementById('save-calibration')?.addEventListener('click', saveCalibrationPoints);
    
    // Clear button
    document.getElementById('clear-calibration')?.addEventListener('click', clearCalibration);
    
    // Canvas click handler
    calibrationCanvas.addEventListener('click', handleCalibrationClick);
    
    // Load saved calibration
    loadCalibrationStatus();
}

// Store the actual calibration image resolution
let calibrationImageWidth = 640;
let calibrationImageHeight = 480;

async function loadCalibrationSnapshot() {
    const btn = document.getElementById('load-snapshot-calibration');
    if (btn) btn.textContent = '⏳ Loading...';
    
    try {
        const response = await fetch('/video_feed?snapshot=1');
        const blob = await response.blob();
        
        calibrationImage = new Image();
        calibrationImage.onload = () => {
            // Store actual image dimensions (camera resolution)
            calibrationImageWidth = calibrationImage.width;
            calibrationImageHeight = calibrationImage.height;
            
            // Set canvas to actual image size for full resolution
            calibrationCanvas.width = calibrationImageWidth;
            calibrationCanvas.height = calibrationImageHeight;
            
            // Mark container as having image
            calibrationCanvas.parentElement.classList.add('has-image');
            
            drawCalibration();
            if (btn) btn.textContent = `📷 Refresh (${calibrationImageWidth}x${calibrationImageHeight})`;
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
    
    // Max 4 points
    if (calibrationPoints.length >= 4) {
        alert('Maximum 4 points. Clear to start over.');
        return;
    }
    
    const rect = calibrationCanvas.getBoundingClientRect();
    // Scale from display size to actual canvas/image resolution
    const scaleX = calibrationCanvas.width / rect.width;
    const scaleY = calibrationCanvas.height / rect.height;
    
    // Coordinates are at full camera resolution
    const px = Math.round((e.clientX - rect.left) * scaleX);
    const py = Math.round((e.clientY - rect.top) * scaleY);
    
    // Ask for world coordinates
    const pointNum = calibrationPoints.length + 1;
    const worldX = prompt(`Point ${pointNum}: Enter X coordinate in meters (left-right):`);
    if (worldX === null || isNaN(parseFloat(worldX))) return;
    
    const worldY = prompt(`Point ${pointNum}: Enter Y coordinate in meters (near-far):`);
    if (worldY === null || isNaN(parseFloat(worldY))) return;
    
    // Add point
    calibrationPoints.push({
        pixel: [px, py],
        world: [parseFloat(worldX), parseFloat(worldY)]
    });
    
    updateCalibrationPointsUI();
    drawCalibration();
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
    
    // Colors for each point
    const colors = ['#ff0000', '#00ff00', '#0000ff', '#ffff00'];
    
    // Draw calibration points
    calibrationPoints.forEach((point, index) => {
        const [px, py] = point.pixel;
        const [wx, wy] = point.world;
        const color = colors[index % colors.length];
        
        // Draw point circle
        calibrationCtx.fillStyle = color;
        calibrationCtx.beginPath();
        calibrationCtx.arc(px, py, 10, 0, Math.PI * 2);
        calibrationCtx.fill();
        
        // Draw white border
        calibrationCtx.strokeStyle = '#fff';
        calibrationCtx.lineWidth = 2;
        calibrationCtx.stroke();
        
        // Draw point number
        calibrationCtx.fillStyle = '#fff';
        calibrationCtx.font = 'bold 14px sans-serif';
        calibrationCtx.textAlign = 'center';
        calibrationCtx.textBaseline = 'middle';
        calibrationCtx.fillText(String(index + 1), px, py);
        
        // Draw world coordinates label
        const label = `(${wx}m, ${wy}m)`;
        calibrationCtx.font = 'bold 12px sans-serif';
        calibrationCtx.textBaseline = 'top';
        
        // Background for label
        const metrics = calibrationCtx.measureText(label);
        calibrationCtx.fillStyle = 'rgba(0,0,0,0.7)';
        calibrationCtx.fillRect(px - metrics.width/2 - 3, py + 15, metrics.width + 6, 18);
        
        calibrationCtx.fillStyle = color;
        calibrationCtx.fillText(label, px, py + 17);
    });
    
    // Draw hint if less than 4 points
    if (calibrationPoints.length < 4) {
        const hint = `Click to add point ${calibrationPoints.length + 1}/4`;
        calibrationCtx.fillStyle = 'rgba(0,0,0,0.7)';
        calibrationCtx.fillRect(10, 10, 200, 25);
        calibrationCtx.fillStyle = '#fff';
        calibrationCtx.font = '14px sans-serif';
        calibrationCtx.textAlign = 'left';
        calibrationCtx.textBaseline = 'middle';
        calibrationCtx.fillText(hint, 20, 22);
    }
}

function updateCalibrationPointsUI() {
    const countEl = document.getElementById('points-count');
    const containerEl = document.getElementById('points-container');
    const saveBtn = document.getElementById('save-calibration');
    
    if (countEl) {
        countEl.textContent = `${calibrationPoints.length}/4`;
    }
    
    // Enable save button only when we have 4 points
    if (saveBtn) {
        saveBtn.disabled = calibrationPoints.length !== 4;
    }
    
    // Build points list HTML
    if (containerEl) {
        containerEl.innerHTML = '';
        const colors = ['#ff0000', '#00ff00', '#0000ff', '#ffff00'];
        
        calibrationPoints.forEach((point, index) => {
            const div = document.createElement('div');
            div.className = 'calibration-point-item';
            div.innerHTML = `
                <span class="point-label" style="color: ${colors[index]}">Point ${index + 1}</span>
                <button class="remove-point" data-index="${index}">✕</button>
                <div class="point-coords">
                    <div>
                        <label>X (m)</label>
                        <input type="number" step="0.1" value="${point.world[0]}" 
                               data-index="${index}" data-coord="x" class="world-coord-input">
                    </div>
                    <div>
                        <label>Y (m)</label>
                        <input type="number" step="0.1" value="${point.world[1]}" 
                               data-index="${index}" data-coord="y" class="world-coord-input">
                    </div>
                </div>
            `;
            containerEl.appendChild(div);
        });
        
        // Add event listeners for remove buttons
        containerEl.querySelectorAll('.remove-point').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const index = parseInt(e.target.dataset.index);
                calibrationPoints.splice(index, 1);
                updateCalibrationPointsUI();
                drawCalibration();
            });
        });
        
        // Add event listeners for world coordinate inputs
        containerEl.querySelectorAll('.world-coord-input').forEach(input => {
            input.addEventListener('change', (e) => {
                const index = parseInt(e.target.dataset.index);
                const coord = e.target.dataset.coord;
                const value = parseFloat(e.target.value) || 0;
                
                if (coord === 'x') {
                    calibrationPoints[index].world[0] = value;
                } else {
                    calibrationPoints[index].world[1] = value;
                }
                drawCalibration();
            });
        });
    }
}

async function loadCalibrationStatus() {
    try {
        const response = await fetch('/api/calibration');
        const data = await response.json();
        
        // Load saved points if any
        if (data.points && Array.isArray(data.points) && data.points.length > 0) {
            calibrationPoints = data.points;
            updateCalibrationPointsUI();
        }
        
        updateCalibrationStatusUI(data);
        
        // Show top-down view if calibrated
        updateTopDownVisibility(data.is_calibrated);
    } catch (error) {
        console.error('Error loading calibration:', error);
    }
}

function updateCalibrationStatusUI(data) {
    const statusEl = document.getElementById('calibration-status');
    if (statusEl) {
        if (data.is_calibrated) {
            statusEl.textContent = 'Calibrated (4 points)';
            statusEl.style.color = '#3fb950';
        } else if (calibrationPoints.length > 0) {
            statusEl.textContent = `${calibrationPoints.length}/4 points defined`;
            statusEl.style.color = '#d29922';
        } else {
            statusEl.textContent = 'Not calibrated';
            statusEl.style.color = '#d29922';
        }
    }
}

async function saveCalibrationPoints() {
    if (calibrationPoints.length !== 4) {
        alert('Need exactly 4 calibration points');
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
            updateCalibrationStatusUI(data.calibration);
            updateTopDownVisibility(data.calibration.is_calibrated);
            alert('Calibration saved successfully!');
            console.log('Calibration saved');
        } else {
            const err = await response.json();
            alert('Calibration failed: ' + (err.error || 'Unknown error'));
        }
    } catch (error) {
        console.error('Error saving calibration:', error);
        alert('Error saving calibration');
    }
}

async function clearCalibration() {
    calibrationPoints = [];
    updateCalibrationPointsUI();
    drawCalibration();
    
    try {
        const response = await fetch('/api/calibration', {
            method: 'DELETE'
        });
        if (response.ok) {
            const data = await response.json();
            updateCalibrationStatusUI(data.calibration || {});
            updateTopDownVisibility(false);
            console.log('Calibration cleared');
        }
    } catch (error) {
        console.error('Error clearing calibration:', error);
    }
}

// ============================================================================
// Top-Down View (Bird's Eye)
// ============================================================================

let topdownCanvas = null;
let topdownCtx = null;
let topdownUpdateInterval = null;

function initTopDownView() {
    topdownCanvas = document.getElementById('topdown-canvas');
    if (!topdownCanvas) return;
    
    topdownCtx = topdownCanvas.getContext('2d');
    
    // Start update loop when visible
    startTopDownUpdates();
}

function updateTopDownVisibility(isCalibrated) {
    const container = document.getElementById('topdown-container');
    if (container) {
        container.style.display = isCalibrated ? 'block' : 'none';
        
        if (isCalibrated && !topdownUpdateInterval) {
            startTopDownUpdates();
        } else if (!isCalibrated && topdownUpdateInterval) {
            stopTopDownUpdates();
        }
    }
}

function startTopDownUpdates() {
    if (topdownUpdateInterval) return;
    
    // Update every 500ms
    topdownUpdateInterval = setInterval(updateTopDownView, 500);
    updateTopDownView(); // Initial update
}

function stopTopDownUpdates() {
    if (topdownUpdateInterval) {
        clearInterval(topdownUpdateInterval);
        topdownUpdateInterval = null;
    }
}

async function updateTopDownView() {
    if (!topdownCanvas || !topdownCtx) {
        topdownCanvas = document.getElementById('topdown-canvas');
        if (!topdownCanvas) return;
        topdownCtx = topdownCanvas.getContext('2d');
    }
    
    try {
        const response = await fetch('/api/topdown');
        const data = await response.json();
        
        if (!data.is_calibrated) {
            updateTopDownVisibility(false);
            return;
        }
        
        drawTopDownView(data);
    } catch (error) {
        console.error('Error updating top-down view:', error);
    }
}

function drawTopDownView(data) {
    const canvas = topdownCanvas;
    const ctx = topdownCtx;
    const bounds = data.world_bounds;
    
    if (!bounds) return;
    
    // Clear canvas
    ctx.fillStyle = '#1a1a2e';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    
    // Calculate scale and offset
    const worldWidth = bounds.max_x - bounds.min_x;
    const worldHeight = bounds.max_y - bounds.min_y;
    
    const padding = 30;
    const availWidth = canvas.width - 2 * padding;
    const availHeight = canvas.height - 2 * padding;
    
    const scale = Math.min(availWidth / worldWidth, availHeight / worldHeight);
    
    // Transform function: world -> canvas
    const toCanvas = (wx, wy) => {
        const cx = padding + (wx - bounds.min_x) * scale;
        // Flip Y axis so positive Y goes up (away from camera)
        const cy = canvas.height - padding - (wy - bounds.min_y) * scale;
        return [cx, cy];
    };
    
    // Draw grid
    ctx.strokeStyle = '#333';
    ctx.lineWidth = 1;
    
    // Vertical lines (every 1m)
    for (let x = Math.ceil(bounds.min_x); x <= bounds.max_x; x++) {
        const [cx1, cy1] = toCanvas(x, bounds.min_y);
        const [cx2, cy2] = toCanvas(x, bounds.max_y);
        ctx.beginPath();
        ctx.moveTo(cx1, cy1);
        ctx.lineTo(cx2, cy2);
        ctx.stroke();
    }
    
    // Horizontal lines (every 1m)
    for (let y = Math.ceil(bounds.min_y); y <= bounds.max_y; y++) {
        const [cx1, cy1] = toCanvas(bounds.min_x, y);
        const [cx2, cy2] = toCanvas(bounds.max_x, y);
        ctx.beginPath();
        ctx.moveTo(cx1, cy1);
        ctx.lineTo(cx2, cy2);
        ctx.stroke();
    }
    
    // Draw perimeter polygon
    if (data.perimeter_world && data.perimeter_world.length >= 3) {
        ctx.fillStyle = 'rgba(0, 255, 0, 0.2)';
        ctx.strokeStyle = '#00ff00';
        ctx.lineWidth = 2;
        
        ctx.beginPath();
        const [startX, startY] = toCanvas(data.perimeter_world[0].x, data.perimeter_world[0].y);
        ctx.moveTo(startX, startY);
        
        for (let i = 1; i < data.perimeter_world.length; i++) {
            const [cx, cy] = toCanvas(data.perimeter_world[i].x, data.perimeter_world[i].y);
            ctx.lineTo(cx, cy);
        }
        
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
    }
    
    // Draw tracked objects
    if (data.objects && data.objects.length > 0) {
        data.objects.forEach(obj => {
            const [cx, cy] = toCanvas(obj.world_x, obj.world_y);
            
            // Draw object as circle
            ctx.fillStyle = '#ff0000';
            ctx.beginPath();
            ctx.arc(cx, cy, 8, 0, Math.PI * 2);
            ctx.fill();
            
            // Draw white border
            ctx.strokeStyle = '#fff';
            ctx.lineWidth = 2;
            ctx.stroke();
            
            // Draw ID
            if (obj.id) {
                ctx.fillStyle = '#fff';
                ctx.font = 'bold 10px sans-serif';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText(String(obj.id), cx, cy);
            }
        });
    }
    
    // Draw scale indicator
    ctx.fillStyle = '#888';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'bottom';
    ctx.fillText(`Scale: 1m = ${scale.toFixed(0)}px`, 5, canvas.height - 5);
    
    // Draw camera indicator at bottom center
    const [camX, camY] = toCanvas((bounds.min_x + bounds.max_x) / 2, bounds.min_y);
    ctx.fillStyle = '#58a6ff';
    ctx.beginPath();
    ctx.moveTo(camX, camY + 10);
    ctx.lineTo(camX - 8, camY + 20);
    ctx.lineTo(camX + 8, camY + 20);
    ctx.closePath();
    ctx.fill();
    ctx.fillText('📷', camX - 6, camY + 35);
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
    
    // Canvas click handler - coordinates are at full camera resolution
    perimeterCanvas.addEventListener('click', (e) => {
        if (!perimeterImage) {
            alert('Please load a camera frame first');
            return;
        }
        
        const rect = perimeterCanvas.getBoundingClientRect();
        // Scale from display size to actual canvas/image resolution
        const scaleX = perimeterCanvas.width / rect.width;
        const scaleY = perimeterCanvas.height / rect.height;
        
        const x = Math.round((e.clientX - rect.left) * scaleX);
        const y = Math.round((e.clientY - rect.top) * scaleY);
        
        // Points are stored at camera resolution
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

// Store the actual image resolution for coordinate conversion
let perimeterImageWidth = 640;
let perimeterImageHeight = 480;

async function loadPerimeterSnapshot() {
    const btn = document.getElementById('load-snapshot-perimeter');
    if (btn) btn.textContent = '⏳ Loading...';
    
    try {
        const response = await fetch('/video_feed?snapshot=1');
        const blob = await response.blob();
        
        perimeterImage = new Image();
        perimeterImage.onload = () => {
            // Store actual image dimensions (camera resolution)
            perimeterImageWidth = perimeterImage.width;
            perimeterImageHeight = perimeterImage.height;
            
            // Set canvas to actual image size for full resolution
            perimeterCanvas.width = perimeterImageWidth;
            perimeterCanvas.height = perimeterImageHeight;
            
            // Mark container as having image
            perimeterCanvas.parentElement.classList.add('has-image');
            
            // Clear existing points when loading new frame
            perimeterPoints = [];
            updatePointsCount();
            
            drawPerimeter();
            if (btn) btn.textContent = `📷 Refresh (${perimeterImageWidth}x${perimeterImageHeight})`;
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
        // Points are already at camera resolution (from the full-res snapshot)
        const response = await fetch('/api/perimeter', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                points: perimeterPoints,
                source_width: perimeterImageWidth,
                source_height: perimeterImageHeight
            })
        });
        
        if (response.ok) {
            alert('Detection zone saved successfully!');
        } else {
            const err = await response.json();
            alert('Error saving zone: ' + (err.error || 'Unknown error'));
        }
    } catch (error) {
        console.error('Error saving perimeter:', error);
        alert('Error saving zone: ' + error.message);
    }
}

async function loadPerimeter() {
    try {
        const response = await fetch('/api/perimeter');
        const data = await response.json();
        
        if (data.points && data.points.length > 0) {
            // Scale points from camera resolution to canvas resolution
            const camWidth = data.resolution ? data.resolution[0] : 640;
            const camHeight = data.resolution ? data.resolution[1] : 480;
            const canvasWidth = perimeterCanvas ? perimeterCanvas.width : 640;
            const canvasHeight = perimeterCanvas ? perimeterCanvas.height : 480;
            
            const scaleX = canvasWidth / camWidth;
            const scaleY = canvasHeight / camHeight;
            
            perimeterPoints = data.points.map(p => [
                Math.round(p[0] * scaleX),
                Math.round(p[1] * scaleY)
            ]);
            
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
        
        // Update overlay CPU display
        const cpuDisplay = document.getElementById('cpu-display');
        if (cpuDisplay && status.cpu_percent !== null) {
            cpuDisplay.textContent = `CPU: ${status.cpu_percent}%`;
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
        await loadThreshold();
        await loadConfirmFrames();
        await loadCalibrationStatus();
        await updateStatus();
        
    } catch (error) {
        console.error('Error loading initial state:', error);
    }
}
