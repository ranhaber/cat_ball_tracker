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
    initVideoSource();
    initLensCalibration();
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
// Stream Resolution Selector (v1.8.0 - capture resolution is now fixed)
// ============================================================================
function initResolutionSelector() {
    // Capture resolution is fixed at 2304x1296
    // Only stream resolution can be changed
    const streamSelector = document.getElementById('stream-resolution-select');
    if (streamSelector) {
        streamSelector.addEventListener('change', (e) => {
            setStreamResolution(e.target.value);
        });
    }
}

async function setStreamResolution(resolutionStr) {
    try {
        // Parse "960x540" into width and height
        const [width, height] = resolutionStr.split('x').map(Number);
        
        const response = await fetch('/api/performance/stream_resolution', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ width, height })
        });
        
        if (response.ok) {
            console.log(`Stream resolution changed to ${width}x${height}`);
            // No need to reconnect video - change applies immediately
        } else {
            const err = await response.json();
            alert('Failed to change stream resolution: ' + (err.error || 'Unknown error'));
        }
    } catch (error) {
        console.error('Error setting stream resolution:', error);
        alert('Error setting stream resolution: ' + error.message);
    }
}

async function loadResolution() {
    try {
        const response = await fetch('/api/performance');
        const data = await response.json();
        
        // Load stream resolution
        const streamSelector = document.getElementById('stream-resolution-select');
        if (streamSelector && data.current && data.current.stream_resolution) {
            const [width, height] = data.current.stream_resolution;
            streamSelector.value = `${width}x${height}`;
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
                    
                    // Reload all UI settings to reflect profile changes
                    await loadThreshold();
                    await loadMotionSettings();
                    await loadConfirmFrames();
                    await updateStatus();
                    
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
let calibrationPoints = [];  // Array of { pixel: [x,y], world?: [x,y] } (world set from side lengths or loaded)
let calibrationSideLengths = [null, null, null, null];  // [L01, L12, L23, L30] in meters
let calibrationDiagonal = null;  // Optional diagonal P0->P2 in meters (for non-rectangle quads)

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
        const response = await fetch('/api/snapshot');
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
    const scaleX = calibrationCanvas.width / rect.width;
    const scaleY = calibrationCanvas.height / rect.height;
    
    const px = Math.round((e.clientX - rect.left) * scaleX);
    const py = Math.round((e.clientY - rect.top) * scaleY);
    
    // Add point (pixel only; world derived from side lengths when saving)
    calibrationPoints.push({ pixel: [px, py] });
    
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
        const hasWorld = point.world && point.world.length === 2;
        const label = hasWorld ? `(${point.world[0].toFixed(1)}m, ${point.world[1].toFixed(1)}m)` : (index === 0 ? '0,0' : `Point ${index + 1}`);
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
        
        // Draw label (world coords or "0,0" / "Point N")
        calibrationCtx.font = 'bold 12px sans-serif';
        calibrationCtx.textBaseline = 'top';
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
    const countEl = document.getElementById('calibration-points-count');
    const containerEl = document.getElementById('points-container');
    const sideLengthsEl = document.getElementById('side-lengths-container');
    const saveBtn = document.getElementById('save-calibration');
    
    if (countEl) {
        countEl.textContent = `${calibrationPoints.length}/4`;
    }
    
    const hasFour = calibrationPoints.length === 4;
    if (saveBtn) {
        saveBtn.disabled = !hasFour || calibrationSideLengths.some(v => v === null || v === '' || isNaN(parseFloat(v)));
    }
    
    // Points list: short labels (Point 1 = 0,0, Point 2, 3, 4) with remove
    if (containerEl) {
        containerEl.innerHTML = '';
        const colors = ['#ff0000', '#00ff00', '#0000ff', '#ffff00'];
        calibrationPoints.forEach((point, index) => {
            const label = index === 0 ? 'Point 1 (origin 0,0)' : `Point ${index + 1}`;
            const div = document.createElement('div');
            div.className = 'calibration-point-item';
            div.innerHTML = `
                <span class="point-label" style="color: ${colors[index]}">${label}</span>
                <button class="remove-point" data-index="${index}">✕</button>
            `;
            containerEl.appendChild(div);
        });
        containerEl.querySelectorAll('.remove-point').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const index = parseInt(e.target.dataset.index);
                calibrationPoints.splice(index, 1);
                calibrationSideLengths = [null, null, null, null];
                updateCalibrationPointsUI();
                drawCalibration();
            });
        });
    }
    
    // Side lengths (shown when 4 points)
    if (sideLengthsEl) {
        if (hasFour) {
            sideLengthsEl.style.display = 'block';
            sideLengthsEl.innerHTML = '<p><strong>Side lengths (meters):</strong></p>' +
                [1, 2, 3, 4].map(i => {
                    const val = calibrationSideLengths[i - 1];
                    const v = val !== null && val !== '' ? val : '';
                    return `<div class="side-length-row">
                        <label>Side ${i} (Point ${i}→${i === 4 ? 1 : i + 1})</label>
                        <input type="number" step="0.01" min="0" data-side="${i - 1}" class="side-length-input" value="${v}" placeholder="meters">
                    </div>`;
                }).join('');
            sideLengthsEl.querySelectorAll('.side-length-input').forEach(input => {
                input.addEventListener('input', (e) => {
                    const idx = parseInt(e.target.dataset.side);
                    const v = e.target.value.trim();
                    calibrationSideLengths[idx] = v === '' ? null : parseFloat(v);
                    if (saveBtn) saveBtn.disabled = calibrationSideLengths.some(v => v === null || v === '' || isNaN(parseFloat(v)));
                });
            });
        } else {
            sideLengthsEl.style.display = 'none';
            sideLengthsEl.innerHTML = '';
        }
    }
    // Diagonal input (shown when 4 points)
    const diagContainer = document.getElementById('diagonal-container');
    if (diagContainer) {
        diagContainer.style.display = hasFour ? 'block' : 'none';
        const diagInput = document.getElementById('calibration-diagonal');
        if (diagInput && calibrationDiagonal !== null && calibrationDiagonal !== '') {
            diagInput.value = calibrationDiagonal;
        }
    }
}

async function loadCalibrationStatus() {
    try {
        const response = await fetch('/api/calibration');
        const data = await response.json();
        
        if (data.points && Array.isArray(data.points) && data.points.length > 0) {
            calibrationPoints = data.points;
            if (data.side_lengths && Array.isArray(data.side_lengths) && data.side_lengths.length === 4) {
                calibrationSideLengths = data.side_lengths.map(v => v);
            }
            updateCalibrationPointsUI();
        }
        
        updateCalibrationStatusUI(data);
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
    const lengths = calibrationSideLengths.map(v => v === null || v === '' ? null : parseFloat(v));
    if (lengths.some(v => v === null || isNaN(v) || v < 0)) {
        alert('Please enter all 4 side lengths (positive numbers in meters)');
        return;
    }
    
    // Read diagonal (optional)
    const diagInput = document.getElementById('calibration-diagonal');
    const diagVal = diagInput ? parseFloat(diagInput.value) : NaN;
    const diagonal = (!isNaN(diagVal) && diagVal > 0) ? diagVal : null;
    
    try {
        const payload = {
            points: calibrationPoints.map(p => ({ pixel: p.pixel })),
            side_lengths: lengths
        };
        if (diagonal !== null) payload.diagonal = diagonal;
        
        const response = await fetch('/api/calibration', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (response.ok) {
            const data = await response.json();
            if (data.calibration && data.calibration.points) {
                calibrationPoints = data.calibration.points;
                if (data.calibration.side_lengths) {
                    calibrationSideLengths = data.calibration.side_lengths.map(v => v);
                }
            }
            updateCalibrationPointsUI();
            drawCalibration();
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
    calibrationSideLengths = [null, null, null, null];
    calibrationDiagonal = null;
    const diagInput = document.getElementById('calibration-diagonal');
    if (diagInput) diagInput.value = '';
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

const TOPDOWN_MARGIN_M = 1;  // 1m margin on each side of the zone for top-down view

function drawTopDownView(data) {
    const canvas = topdownCanvas;
    const ctx = topdownCtx;
    // Bounds: use Detection Zone extent + 1m margin each direction when we have perimeter; else backend world_bounds
    let bounds = data.world_bounds;
    if (data.perimeter_world && data.perimeter_world.length >= 1) {
        const px = data.perimeter_world.map(p => p.x);
        const py = data.perimeter_world.map(p => p.y);
        bounds = {
            min_x: Math.min(...px) - TOPDOWN_MARGIN_M,
            max_x: Math.max(...px) + TOPDOWN_MARGIN_M,
            min_y: Math.min(...py) - TOPDOWN_MARGIN_M,
            max_y: Math.max(...py) + TOPDOWN_MARGIN_M
        };
    }
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
    
    // Draw X and Y axes and (0,0) at the first Detection Zone polygon point so they match
    const originWorld = data.perimeter_world && data.perimeter_world.length >= 1
        ? { x: data.perimeter_world[0].x, y: data.perimeter_world[0].y }
        : (bounds.min_x <= 0 && 0 <= bounds.max_x && bounds.min_y <= 0 && 0 <= bounds.max_y ? { x: 0, y: 0 } : null);
    if (originWorld) {
        const [ox, oy] = toCanvas(originWorld.x, originWorld.y);
        const inBounds = bounds.min_x <= originWorld.x && originWorld.x <= bounds.max_x &&
            bounds.min_y <= originWorld.y && originWorld.y <= bounds.max_y;
        if (inBounds) {
            // Y axis through first zone point: vertical line
            ctx.strokeStyle = '#ff8c00';
            ctx.lineWidth = 2;
            ctx.setLineDash([4, 4]);
            ctx.beginPath();
            ctx.moveTo(ox, toCanvas(originWorld.x, bounds.min_y)[1]);
            ctx.lineTo(ox, toCanvas(originWorld.x, bounds.max_y)[1]);
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.fillStyle = '#ff8c00';
            ctx.font = '11px sans-serif';
            ctx.textAlign = 'right';
            ctx.fillText('+Y', ox - 6, toCanvas(originWorld.x, bounds.max_y)[1] - 4);
            // X axis through first zone point: horizontal line
            ctx.strokeStyle = '#00bfff';
            ctx.beginPath();
            ctx.moveTo(toCanvas(bounds.min_x, originWorld.y)[0], oy);
            ctx.lineTo(toCanvas(bounds.max_x, originWorld.y)[0], oy);
            ctx.stroke();
            ctx.fillStyle = '#00bfff';
            ctx.textAlign = 'left';
            ctx.fillText('+X', toCanvas(bounds.max_x, originWorld.y)[0] + 4, oy + 4);
            // Origin label (0,0) at first zone point
            ctx.fillStyle = '#fff';
            ctx.font = 'bold 11px sans-serif';
            ctx.textAlign = 'left';
            ctx.textBaseline = 'top';
            ctx.fillText('(0,0)', ox + 4, oy + 2);
            ctx.strokeStyle = '#fff';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.arc(ox, oy, 4, 0, Math.PI * 2);
            ctx.stroke();
        }
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
        
        // Draw all Detection Zone polygon points (vertices) with labels
        data.perimeter_world.forEach((point, index) => {
            const [cx, cy] = toCanvas(point.x, point.y);
            ctx.fillStyle = '#00ff00';
            ctx.beginPath();
            ctx.arc(cx, cy, 6, 0, Math.PI * 2);
            ctx.fill();
            ctx.strokeStyle = '#000';
            ctx.lineWidth = 1;
            ctx.stroke();
            const label = index === 0 ? '(0,0)' : String(index + 1);
            ctx.fillStyle = '#fff';
            ctx.font = 'bold 11px sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'bottom';
            ctx.fillText(label, cx, cy - 8);
        });
        
        // Draw side lengths near the center of each side (in meters)
        const n = data.perimeter_world.length;
        for (let i = 0; i < n; i++) {
            const a = data.perimeter_world[i];
            const b = data.perimeter_world[(i + 1) % n];
            const dx = b.x - a.x;
            const dy = b.y - a.y;
            const len = Math.sqrt(dx * dx + dy * dy);
            const midX = (a.x + b.x) / 2;
            const midY = (a.y + b.y) / 2;
            const [mcx, mcy] = toCanvas(midX, midY);
            const text = len >= 1 ? `${len.toFixed(2)} m` : `${(len * 100).toFixed(0)} cm`;
            ctx.font = '11px sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            const tw = ctx.measureText(text).width;
            const th = 14;
            ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
            ctx.fillRect(mcx - tw / 2 - 4, mcy - th / 2 - 2, tw + 8, th + 4);
            ctx.fillStyle = '#b0ffb0';
            ctx.fillText(text, mcx, mcy);
        }
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
    
    document.getElementById('clear-perimeter')?.addEventListener('click', async () => {
        perimeterPoints = [];
        if (perimeterCanvas) {
            // Force canvas buffer clear (resetting width/height clears the canvas in HTML5)
            const w = perimeterCanvas.width;
            const h = perimeterCanvas.height;
            perimeterCanvas.width = w;
            perimeterCanvas.height = h;
        }
        drawPerimeter();
        updatePointsCount();
        try {
            await fetch('/api/perimeter', { method: 'DELETE' });
        } catch (e) {
            console.warn('Clear perimeter on server failed:', e);
        }
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
        const response = await fetch('/api/snapshot');
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
    if (!perimeterCtx || !perimeterCanvas) return;
    
    // Always clear canvas first so "Clear Points" fully erases the polygon
    perimeterCtx.clearRect(0, 0, perimeterCanvas.width, perimeterCanvas.height);
    
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
    
    const p0 = perimeterPoints[0];
    const axisLen = Math.min(perimeterCanvas.width, perimeterCanvas.height) * 0.12;
    
    // Coordinate system: origin at first point (0,0), X right, Y up (image Y down)
    perimeterCtx.lineWidth = 2;
    perimeterCtx.lineCap = 'round';
    // +X axis (to the right)
    perimeterCtx.strokeStyle = '#00bfff';
    perimeterCtx.beginPath();
    perimeterCtx.moveTo(p0[0], p0[1]);
    perimeterCtx.lineTo(p0[0] + axisLen, p0[1]);
    perimeterCtx.stroke();
    perimeterCtx.fillStyle = '#00bfff';
    perimeterCtx.font = 'bold 12px sans-serif';
    perimeterCtx.textAlign = 'left';
    perimeterCtx.fillText('+X', p0[0] + axisLen + 4, p0[1] + 4);
    // +Y axis (up in world = decreasing y in image)
    perimeterCtx.strokeStyle = '#ff8c00';
    perimeterCtx.beginPath();
    perimeterCtx.moveTo(p0[0], p0[1]);
    perimeterCtx.lineTo(p0[0], p0[1] - axisLen);
    perimeterCtx.stroke();
    perimeterCtx.fillStyle = '#ff8c00';
    perimeterCtx.textAlign = 'right';
    perimeterCtx.fillText('+Y', p0[0] - 4, p0[1] - axisLen - 4);
    
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
    
    // Draw points and labels
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
        
        // Label: first point as (0,0), others as 2, 3, 4...
        const label = index === 0 ? '(0,0)' : String(index + 1);
        perimeterCtx.fillStyle = '#fff';
        perimeterCtx.font = index === 0 ? 'bold 14px sans-serif' : 'bold 14px sans-serif';
        perimeterCtx.textAlign = 'center';
        perimeterCtx.strokeStyle = '#000';
        perimeterCtx.lineWidth = 3;
        perimeterCtx.strokeText(label, point[0], point[1] - 15);
        perimeterCtx.fillText(label, point[0], point[1] - 15);
    });
}

function updatePointsCount() {
    const el = document.getElementById('perimeter-points-count');
    if (el) el.textContent = `Points: ${perimeterPoints.length} (minimum 3 required)`;
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

        const versionEl = document.getElementById('version');
        if (versionEl && status.version) versionEl.textContent = `v${status.version}`;
        
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
        await loadLensCalibrationStatus();
        await loadCurrentProfile();
        await loadVideoSource();
        await updateStatus();
        
    } catch (error) {
        console.error('Error loading initial state:', error);
    }
}

async function loadCurrentProfile() {
    try {
        const response = await fetch('/api/performance/profile');
        if (response.ok) {
            const data = await response.json();
            const profileValue = data.profile;
            
            // Update the UI to show the current profile
            const profileRadio = document.querySelector(`input[name="profile"][value="${profileValue}"]`);
            if (profileRadio) {
                profileRadio.checked = true;
                console.log(`Current profile loaded: ${profileValue}`);
            }
        }
    } catch (error) {
        console.error('Error loading current profile:', error);
    }
}

// ============================================================================
// Video Source & Recording (Video tab)
// ============================================================================
function initVideoSource() {
    const liveRadio = document.getElementById('video-source-live');
    const fileRadio = document.getElementById('video-source-file');
    const filePanel = document.getElementById('video-file-panel');
    const librarySelect = document.getElementById('video-library-select');
    const loadLibraryBtn = document.getElementById('video-load-library-btn');
    const pathInput = document.getElementById('video-file-path-input');
    const loadPathBtn = document.getElementById('video-load-path-btn');
    const recordingCheckbox = document.getElementById('recording-enabled-checkbox');
    const recordAfterSec = document.getElementById('record-after-sec');

    if (!liveRadio || !fileRadio) return;

    function showFilePanel(show) {
        filePanel.style.display = show ? 'block' : 'none';
    }

    liveRadio.addEventListener('change', async () => {
        if (!liveRadio.checked) return;
        showFilePanel(false);
        try {
            const res = await fetch('/api/video/source', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ video_source: 'live' })
            });
            const data = await res.json();
            if (data.success) console.log('Switched to live camera');
        } catch (e) { console.error(e); }
    });

    fileRadio.addEventListener('change', () => {
        showFilePanel(fileRadio.checked);
        if (fileRadio.checked) loadVideoLibrary();
    });

    const libraryPathInput = document.getElementById('video-library-path-input');
    const refreshLibraryBtn = document.getElementById('video-refresh-library-btn');
    if (refreshLibraryBtn) refreshLibraryBtn.addEventListener('click', () => {
        const path = (libraryPathInput && libraryPathInput.value.trim()) || null;
        loadVideoLibrary(path);
    });

    loadLibraryBtn.addEventListener('click', async () => {
        const path = librarySelect.value;
        if (!path) return;
        try {
            const res = await fetch('/api/video/source', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ video_source: 'file', video_file_path: path })
            });
            const data = await res.json();
            if (data.success) console.log('Loading file:', path);
            else alert(data.error || 'Failed to load file');
        } catch (e) { console.error(e); alert('Request failed'); }
    });

    loadPathBtn.addEventListener('click', async () => {
        const path = (pathInput.value || '').trim();
        if (!path) return;
        try {
            const res = await fetch('/api/video/source', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ video_source: 'file', video_file_path: path })
            });
            const data = await res.json();
            if (data.success) console.log('Loading file:', path);
            else alert(data.error || 'Failed to load file');
        } catch (e) { console.error(e); alert('Request failed'); }
    });

    recordingCheckbox.addEventListener('change', async () => {
        try {
            await fetch('/api/video/recording', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ recording_enabled: recordingCheckbox.checked })
            });
        } catch (e) { console.error(e); }
    });

    recordAfterSec.addEventListener('change', () => {
        const sec = parseInt(recordAfterSec.value, 10);
        if (sec >= 1 && sec <= 60) {
            fetch('/api/video/recording', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ record_after_detection_sec: sec })
            }).catch(e => console.error(e));
        }
    });
}

async function loadVideoLibrary(customPath) {
    const select = document.getElementById('video-library-select');
    const pathInput = document.getElementById('video-library-path-input');
    if (!select) return;
    try {
        const url = customPath != null ? `/api/video/library?path=${encodeURIComponent(customPath)}` : '/api/video/library';
        const res = await fetch(url);
        const data = await res.json();
        if (pathInput) pathInput.value = data.path || '';
        select.innerHTML = '<option value="">-- Select file --</option>';
        (data.files || []).forEach(f => {
            const opt = document.createElement('option');
            opt.value = f.path;
            opt.textContent = f.name;
            select.appendChild(opt);
        });
    } catch (e) { console.error(e); }
}

async function loadVideoSource() {
    try {
        const res = await fetch('/api/video/source');
        const data = await res.json();
        const liveRadio = document.getElementById('video-source-live');
        const fileRadio = document.getElementById('video-source-file');
        const filePanel = document.getElementById('video-file-panel');
        const recordingCheckbox = document.getElementById('recording-enabled-checkbox');
        const recordAfterSec = document.getElementById('record-after-sec');
        const pathInput = document.getElementById('video-library-path-input');
        if (!liveRadio || !fileRadio) return;
        liveRadio.checked = data.video_source === 'live';
        fileRadio.checked = data.video_source === 'file';
        filePanel.style.display = data.video_source === 'file' ? 'block' : 'none';
        if (pathInput) pathInput.value = data.video_library_path || '';
        if (recordingCheckbox !== null) recordingCheckbox.checked = data.recording_enabled !== false;
        if (recordAfterSec !== null) recordAfterSec.value = data.record_after_detection_sec || 5;
        if (data.video_source === 'file') await loadVideoLibrary();
    } catch (e) { console.error(e); }
}

// ============================================================================
// Lens Calibration (Plumb-Line Method)
// ============================================================================
let lensCanvas, lensCtx, lensImage = null;
let lensSavedLines = [];     // lines saved to file on server
let lensUnsavedLines = [];   // lines added since last save (in memory only)
let lensCurrentLine = [];    // points of the line currently being drawn
let lensImageWidth = 640, lensImageHeight = 480;
const LENS_TARGET_LINES = 6;

function initLensCalibration() {
    lensCanvas = document.getElementById('lens-canvas');
    if (!lensCanvas) return;
    lensCtx = lensCanvas.getContext('2d');

    document.getElementById('load-snapshot-lens')?.addEventListener('click', loadLensSnapshot);
    document.getElementById('lens-add-line')?.addEventListener('click', lensAddLine);
    document.getElementById('lens-undo-point')?.addEventListener('click', lensUndoPoint);
    document.getElementById('lens-save-lines')?.addEventListener('click', lensSaveLines);
    document.getElementById('lens-calibrate')?.addEventListener('click', lensRunCalibration);
    document.getElementById('lens-clear')?.addEventListener('click', lensClearFile);
    document.getElementById('lens-export')?.addEventListener('click', lensExportLines);
    document.getElementById('lens-import')?.addEventListener('click', () => document.getElementById('lens-import-file')?.click());
    document.getElementById('lens-import-file')?.addEventListener('change', lensImportLines);

    lensCanvas.addEventListener('click', (e) => {
        if (!lensImage) { alert('Load a camera frame first'); return; }
        const rect = lensCanvas.getBoundingClientRect();
        const sx = lensCanvas.width / rect.width;
        const sy = lensCanvas.height / rect.height;
        const x = Math.round((e.clientX - rect.left) * sx);
        const y = Math.round((e.clientY - rect.top) * sy);
        lensCurrentLine.push([x, y]);
        drawLensCanvas();
        updateLensUI();
    });
}

// 1. Load Frame -- just loads a new picture, touches nothing else
async function loadLensSnapshot() {
    const btn = document.getElementById('load-snapshot-lens');
    if (btn) btn.textContent = '⏳ Loading...';
    try {
        const response = await fetch('/api/snapshot');
        const blob = await response.blob();
        lensImage = new Image();
        lensImage.onload = () => {
            lensImageWidth = lensImage.width;
            lensImageHeight = lensImage.height;
            lensCanvas.width = lensImageWidth;
            lensCanvas.height = lensImageHeight;
            lensCanvas.parentElement.classList.add('has-image');
            drawLensCanvas();
            updateLensUI();
            if (btn) btn.textContent = `📷 Load Frame (${lensImageWidth}x${lensImageHeight})`;
        };
        lensImage.src = URL.createObjectURL(blob);
    } catch (err) {
        console.error('Lens snapshot error:', err);
        if (btn) btn.textContent = '📷 Load Frame';
    }
}

// 2. Add Line -- moves current line to unsaved list (memory only, NOT saved to file)
function lensAddLine() {
    if (lensCurrentLine.length >= 3) {
        lensUnsavedLines.push([...lensCurrentLine]);
    } else if (lensCurrentLine.length > 0) {
        alert('A line needs at least 3 points.');
        return;
    }
    lensCurrentLine = [];
    drawLensCanvas();
    updateLensUI();
}

// 3. Undo Point
function lensUndoPoint() {
    if (lensCurrentLine.length > 0) {
        lensCurrentLine.pop();
    } else if (lensUnsavedLines.length > 0) {
        lensCurrentLine = lensUnsavedLines.pop();
    }
    drawLensCanvas();
    updateLensUI();
}

// 4. Save Lines -- saves all unsaved lines to the server file
async function lensSaveLines() {
    // Finalize current line if 3+ points
    if (lensCurrentLine.length >= 3) {
        lensUnsavedLines.push([...lensCurrentLine]);
        lensCurrentLine = [];
    }
    if (lensUnsavedLines.length === 0) {
        alert('No new lines to save.');
        return;
    }
    const btn = document.getElementById('lens-save-lines');
    if (btn) btn.textContent = '⏳ Saving...';
    try {
        let saved = 0;
        for (const line of lensUnsavedLines) {
            const response = await fetch('/api/lens_calibration/lines/append', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ points: line, image_width: lensImageWidth, image_height: lensImageHeight })
            });
            if (response.ok) saved++;
        }
        // Move unsaved to saved
        lensSavedLines.push(...lensUnsavedLines);
        lensUnsavedLines = [];
        alert(`Saved ${saved} new lines. Total saved: ${lensSavedLines.length}`);
    } catch (err) {
        console.error('Save lines error:', err);
        alert('Error saving lines');
    }
    if (btn) btn.textContent = '💾 Save Lines';
    drawLensCanvas();
    updateLensUI();
}

// 5. Calibrate
async function lensRunCalibration() {
    // All saved + unsaved + current (if 3+)
    const allLines = [...lensSavedLines, ...lensUnsavedLines];
    if (lensCurrentLine.length >= 3) allLines.push([...lensCurrentLine]);
    if (allLines.length < 2) {
        alert(`Need at least 2 lines (3+ points each).\nCurrently: ${lensSavedLines.length} saved, ${lensUnsavedLines.length} unsaved.`);
        return;
    }
    if (!lensImageWidth || !lensImageHeight || lensImageWidth <= 1 || lensImageHeight <= 1) {
        alert('Image dimensions unknown. Load a camera frame first.');
        return;
    }
    const calibBtn = document.getElementById('lens-calibrate');
    const statusEl = document.getElementById('lens-status');
    if (calibBtn) { calibBtn.textContent = '⏳ 0/2000'; calibBtn.disabled = true; }
    if (statusEl) { statusEl.textContent = 'Calibrating... iteration 0/2000'; statusEl.style.color = '#d29922'; }
    console.log(`[LENS] Calibrating: ${allLines.length} lines, ${lensImageWidth}x${lensImageHeight}`);

    // Poll progress every second while calibrating
    const progressInterval = setInterval(async () => {
        try {
            const pr = await fetch('/api/lens_calibration/progress');
            const pg = await pr.json();
            if (pg.in_progress) {
                const iter100 = Math.floor(pg.iteration / 100) * 100;
                if (calibBtn) calibBtn.textContent = `⏳ ${iter100}/${pg.max_iterations}`;
                if (statusEl) statusEl.textContent = `Calibrating... iteration ${iter100}/${pg.max_iterations}`;
            }
        } catch (e) { /* ignore polling errors */ }
    }, 1000);

    try {
        const response = await fetch('/api/lens_calibration', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                lines: allLines,
                image_width: lensImageWidth,
                image_height: lensImageHeight
            })
        });
        clearInterval(progressInterval);
        const data = await response.json();
        console.log('[LENS] Response:', response.status, data);
        if (response.ok && data.success) {
            const c = data.calibration;
            let msg = `Lens calibration done!\n\n`;
            msg += `k1 = ${c.k1}, k2 = ${c.k2}, k3 = ${c.k3}\n`;
            msg += `p1 = ${c.p1}, p2 = ${c.p2}\n`;
            msg += `f = ${c.fx}, cx = ${c.cx}, cy = ${c.cy}\n\n`;
            msg += `Overall: ${c.overall_improvement_pct}% improvement\n`;
            msg += `  Before: ${c.overall_before_mean_px} px mean deviation\n`;
            msg += `  After:  ${c.overall_after_mean_px} px mean deviation\n\n`;
            msg += `Per line:\n`;
            c.line_errors.forEach(e => {
                msg += `  L${e.line} (${e.points} pts): ${e.before_mean_px}px → ${e.after_mean_px}px (${e.improvement_pct}% better)\n`;
            });
            alert(msg);
            updateLensStatusUI({...c, is_calibrated: true, num_lines: allLines.length, total_points: allLines.reduce((s,l) => s + l.length, 0)});
        } else {
            alert('Calibration failed: ' + (data.error || 'Unknown error'));
        }
    } catch (err) {
        clearInterval(progressInterval);
        console.error('Lens calibration error:', err);
        alert('Calibration error: ' + err.message);
        if (statusEl) { statusEl.textContent = 'Calibration failed'; statusEl.style.color = '#ff4444'; }
    }
    if (calibBtn) { calibBtn.textContent = '🔧 Calibrate'; calibBtn.disabled = false; }
}

// 6. Export Lines -- download saved lines from server as JSON
async function lensExportLines() {
    try {
        const response = await fetch('/api/lens_calibration/lines');
        const data = await response.json();
        if (!data.lines || data.lines.length === 0) { alert('No saved lines to export'); return; }
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'lens_lines.json';
        a.click();
        URL.revokeObjectURL(url);
    } catch (err) { console.error('Export error:', err); alert('Export failed'); }
}

// 7. Import Lines -- upload JSON file, replaces saved lines on server
async function lensImportLines(e) {
    const file = e.target.files[0];
    if (!file) return;
    try {
        const text = await file.text();
        const response = await fetch('/api/lens_calibration/lines', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: text
        });
        const result = await response.json();
        if (response.ok && result.success) {
            lensSavedLines = result.lines || [];
            lensUnsavedLines = [];
            lensCurrentLine = [];
            lensImageWidth = result.image_width || 640;
            lensImageHeight = result.image_height || 480;
            drawLensCanvas();
            updateLensUI();
            alert(`Imported ${result.num_lines} lines (${result.total_points} points).`);
        } else {
            alert('Import failed: ' + (result.error || 'Unknown error'));
        }
    } catch (err) {
        console.error('Import error:', err);
        alert('Failed to read file: ' + err.message);
    }
    e.target.value = '';
}

// 8. Clear Lines File -- deletes saved lines AND calibration
async function lensClearFile() {
    if (!confirm('Delete all saved lines and calibration?')) return;
    lensSavedLines = [];
    lensUnsavedLines = [];
    lensCurrentLine = [];
    drawLensCanvas();
    updateLensUI();
    updateLensStatusUI({ is_calibrated: false });
    try {
        await fetch('/api/lens_calibration', { method: 'DELETE' });
    } catch (e) { console.warn('Clear failed:', e); }
}

function updateLensUI() {
    const savedCount = lensSavedLines.length;
    const unsavedCount = lensUnsavedLines.length + (lensCurrentLine.length >= 3 ? 1 : 0);
    const totalLines = savedCount + unsavedCount;

    const savedEl = document.getElementById('lens-saved-count');
    const unsavedEl = document.getElementById('lens-unsaved-count');
    const pointCountEl = document.getElementById('lens-point-count');
    const progressBar = document.getElementById('lens-progress-bar');
    const addLineBtn = document.getElementById('lens-add-line');
    const undoBtn = document.getElementById('lens-undo-point');
    const saveBtn = document.getElementById('lens-save-lines');
    const calibBtn = document.getElementById('lens-calibrate');
    const exportBtn = document.getElementById('lens-export');

    if (savedEl) savedEl.textContent = savedCount;
    if (unsavedEl) unsavedEl.textContent = lensUnsavedLines.length + (lensCurrentLine.length >= 3 ? 1 : 0);
    if (pointCountEl) pointCountEl.textContent = lensCurrentLine.length;
    if (progressBar) {
        const pct = Math.min(100, Math.round((savedCount / LENS_TARGET_LINES) * 100));
        progressBar.style.width = pct + '%';
        progressBar.style.background = savedCount >= LENS_TARGET_LINES ? '#3fb950' : '#d29922';
    }
    if (addLineBtn) addLineBtn.disabled = !lensImage || lensCurrentLine.length < 3;
    if (undoBtn) undoBtn.disabled = (lensCurrentLine.length === 0 && lensUnsavedLines.length === 0);
    if (saveBtn) saveBtn.disabled = (lensUnsavedLines.length === 0 && lensCurrentLine.length < 3);
    if (calibBtn) {
        calibBtn.disabled = totalLines < 2;
        if (totalLines >= 2 && totalLines < LENS_TARGET_LINES) {
            calibBtn.textContent = `🔧 Calibrate (${totalLines}/${LENS_TARGET_LINES})`;
        } else {
            calibBtn.textContent = '🔧 Calibrate';
        }
    }
    if (exportBtn) exportBtn.disabled = savedCount === 0;
}

const LINE_COLORS = ['#ff4444', '#44ff44', '#4488ff', '#ffff44', '#ff44ff', '#44ffff', '#ff8844', '#88ff44'];

function drawLensCanvas() {
    if (!lensCtx || !lensCanvas) return;
    lensCtx.clearRect(0, 0, lensCanvas.width, lensCanvas.height);
    if (lensImage) {
        lensCtx.drawImage(lensImage, 0, 0, lensCanvas.width, lensCanvas.height);
    } else {
        lensCtx.fillStyle = '#000';
        lensCtx.fillRect(0, 0, lensCanvas.width, lensCanvas.height);
    }
    let lineNum = 0;
    // Draw saved lines (solid)
    lensSavedLines.forEach((line) => {
        lineNum++;
        drawLensLine(line, LINE_COLORS[(lineNum - 1) % LINE_COLORS.length], lineNum, false);
    });
    // Draw unsaved lines (dashed, slightly transparent)
    lensUnsavedLines.forEach((line) => {
        lineNum++;
        drawLensLine(line, LINE_COLORS[(lineNum - 1) % LINE_COLORS.length], lineNum, true);
    });
    // Draw current line being drawn (dashed)
    if (lensCurrentLine.length > 0) {
        lineNum++;
        drawLensLine(lensCurrentLine, LINE_COLORS[(lineNum - 1) % LINE_COLORS.length], lineNum, true);
    }
}

function drawLensLine(points, color, lineNum, isCurrent) {
    if (points.length < 2) {
        // Single point
        if (points.length === 1) {
            lensCtx.fillStyle = color;
            lensCtx.beginPath();
            lensCtx.arc(points[0][0], points[0][1], 6, 0, Math.PI * 2);
            lensCtx.fill();
        }
        return;
    }
    // Line through points
    lensCtx.strokeStyle = color;
    lensCtx.lineWidth = 2;
    if (isCurrent) lensCtx.setLineDash([6, 4]);
    lensCtx.beginPath();
    lensCtx.moveTo(points[0][0], points[0][1]);
    for (let i = 1; i < points.length; i++) {
        lensCtx.lineTo(points[i][0], points[i][1]);
    }
    lensCtx.stroke();
    lensCtx.setLineDash([]);
    // Points
    points.forEach((p, idx) => {
        lensCtx.fillStyle = color;
        lensCtx.beginPath();
        lensCtx.arc(p[0], p[1], 5, 0, Math.PI * 2);
        lensCtx.fill();
        lensCtx.strokeStyle = '#000';
        lensCtx.lineWidth = 1;
        lensCtx.stroke();
    });
    // Line label
    const mid = points[Math.floor(points.length / 2)];
    lensCtx.fillStyle = '#fff';
    lensCtx.font = 'bold 13px sans-serif';
    lensCtx.textAlign = 'center';
    lensCtx.strokeStyle = '#000';
    lensCtx.lineWidth = 3;
    lensCtx.strokeText(`L${lineNum}`, mid[0], mid[1] - 12);
    lensCtx.fillText(`L${lineNum}`, mid[0], mid[1] - 12);
}

async function lensRunCalibration() {
    // Finalise current line if it has 3+ points
    const allLines = [...lensLines];
    if (lensCurrentLine.length >= 3) {
        allLines.push([...lensCurrentLine]);
    }
    if (allLines.length < 2) {
        alert('Need at least 2 completed lines (3+ points each)');
        return;
    }
    const calibBtn = document.getElementById('lens-calibrate');
    if (calibBtn) calibBtn.textContent = '⏳ Calibrating...';
    try {
        const response = await fetch('/api/lens_calibration', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                lines: allLines,
                image_width: lensImageWidth,
                image_height: lensImageHeight
            })
        });
        const data = await response.json();
        if (response.ok && data.success) {
            const c = data.calibration;
            let msg = `Lens calibration done!\n\n`;
            msg += `k1 = ${c.k1}, k2 = ${c.k2}\n\n`;
            msg += `Overall: ${c.overall_improvement_pct}% improvement\n`;
            msg += `  Before: ${c.overall_before_mean_px} px mean deviation\n`;
            msg += `  After:  ${c.overall_after_mean_px} px mean deviation\n\n`;
            msg += `Per line:\n`;
            c.line_errors.forEach(e => {
                msg += `  L${e.line} (${e.points} pts): ${e.before_mean_px}px → ${e.after_mean_px}px (${e.improvement_pct}% better)\n`;
            });
            alert(msg);
            lensLines = allLines;
            lensCurrentLine = [];
            drawLensCanvas();
            updateLensUI();
            updateLensStatusUI({...c, is_calibrated: true, num_lines: allLines.length, total_points: allLines.reduce((s,l) => s + l.length, 0)});
        } else {
            alert('Calibration failed: ' + (data.error || 'Unknown error'));
        }
    } catch (err) {
        console.error('Lens calibration error:', err);
        alert('Error: ' + err.message);
    }
    if (calibBtn) calibBtn.textContent = '🔧 Calibrate';
}

async function loadLensCalibrationStatus() {
    try {
        const response = await fetch('/api/lens_calibration');
        const data = await response.json();
        updateLensStatusUI(data);
    } catch (err) {
        console.error('Error loading lens calibration status:', err);
    }
    // Load saved lines from persistent file
    try {
        const response = await fetch('/api/lens_calibration/lines');
        const data = await response.json();
        if (data.lines && data.lines.length > 0) {
            lensSavedLines = data.lines;
            lensUnsavedLines = [];
            lensCurrentLine = [];
            if (data.image_width) lensImageWidth = data.image_width;
            if (data.image_height) lensImageHeight = data.image_height;
            if (lensCanvas) {
                lensCanvas.width = lensImageWidth;
                lensCanvas.height = lensImageHeight;
            }
            drawLensCanvas();
            updateLensUI();
            console.log(`[LENS] Loaded ${lensSavedLines.length} saved lines`);
        }
    } catch (err) {
        console.error('Error loading saved lens lines:', err);
    }
}

function updateLensStatusUI(data) {
    const statusEl = document.getElementById('lens-status');
    const paramsEl = document.getElementById('lens-params');
    if (!statusEl) return;
    if (data && data.is_calibrated) {
        let statusText = `Calibrated (${data.num_lines} lines, ${data.total_points} points)`;
        if (data.overall_improvement_pct !== undefined) {
            statusText += ` — ${data.overall_improvement_pct}% improvement`;
        }
        statusEl.textContent = statusText;
        statusEl.style.color = '#3fb950';
        if (paramsEl) {
            paramsEl.style.display = 'block';
            let info = `f=${data.fx} | k1=${data.k1}, k2=${data.k2}, k3=${data.k3 || 0}`;
            if (data.p1 || data.p2) info += ` | p1=${data.p1}, p2=${data.p2}`;
            if (data.overall_before_mean_px !== undefined) {
                info += ` | deviation: ${data.overall_before_mean_px}px → ${data.overall_after_mean_px}px`;
            }
            paramsEl.textContent = info;
        }
    } else {
        statusEl.textContent = 'Not calibrated';
        statusEl.style.color = '#d29922';
        if (paramsEl) paramsEl.style.display = 'none';
    }
}
