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

function initPerimeterEditor() {
    perimeterCanvas = document.getElementById('perimeter-canvas');
    if (!perimeterCanvas) return;
    
    perimeterCtx = perimeterCanvas.getContext('2d');
    
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
    
    document.getElementById('clear-perimeter')?.addEventListener('click', () => {
        perimeterPoints = [];
        drawPerimeter();
        updatePointsCount();
    });
    
    document.getElementById('save-perimeter')?.addEventListener('click', savePerimeter);
}

function drawPerimeter() {
    if (!perimeterCtx) return;
    
    perimeterCtx.fillStyle = '#000';
    perimeterCtx.fillRect(0, 0, perimeterCanvas.width, perimeterCanvas.height);
    
    // Draw grid
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
    
    if (perimeterPoints.length === 0) {
        perimeterCtx.fillStyle = '#666';
        perimeterCtx.font = '16px sans-serif';
        perimeterCtx.textAlign = 'center';
        perimeterCtx.fillText('Click to add perimeter points', perimeterCanvas.width / 2, perimeterCanvas.height / 2);
        return;
    }
    
    // Draw polygon
    if (perimeterPoints.length >= 2) {
        perimeterCtx.strokeStyle = '#58a6ff';
        perimeterCtx.lineWidth = 2;
        perimeterCtx.beginPath();
        perimeterCtx.moveTo(perimeterPoints[0][0], perimeterPoints[0][1]);
        
        for (let i = 1; i < perimeterPoints.length; i++) {
            perimeterCtx.lineTo(perimeterPoints[i][0], perimeterPoints[i][1]);
        }
        
        if (perimeterPoints.length >= 3) {
            perimeterCtx.closePath();
            perimeterCtx.fillStyle = 'rgba(88, 166, 255, 0.1)';
            perimeterCtx.fill();
        }
        
        perimeterCtx.stroke();
    }
    
    // Draw points
    perimeterPoints.forEach((point, index) => {
        perimeterCtx.fillStyle = '#58a6ff';
        perimeterCtx.beginPath();
        perimeterCtx.arc(point[0], point[1], 6, 0, Math.PI * 2);
        perimeterCtx.fill();
        
        perimeterCtx.fillStyle = '#fff';
        perimeterCtx.font = '12px sans-serif';
        perimeterCtx.textAlign = 'center';
        perimeterCtx.fillText(String(index + 1), point[0], point[1] - 12);
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
        await updateStatus();
        
    } catch (error) {
        console.error('Error loading initial state:', error);
    }
}
