/**
 * AI Meeting Note Taker - Popup Script
 * 
 * Handles UI events and communicates with the background service worker.
 * All sensitive operations (transcription, notes) happen on the API server.
 */

// State
let isRecording = false;
let isConnected = false;
let transcriptLines = [];
let currentNotes = null;
let syncInterval = null;

// DOM Elements
const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');
const statusBar = document.getElementById('statusBar');
const statusText = document.getElementById('statusText');
const connectionStatus = document.getElementById('connectionStatus');
const connectionText = document.getElementById('connectionText');
const transcriptPanel = document.getElementById('transcriptPanel');
const notesPanel = document.getElementById('notesPanel');
const downloadSection = document.getElementById('downloadSection');
const tabs = document.querySelectorAll('.tab');

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
    // Load state from storage
    const state = await chrome.storage.local.get(['isRecording', 'transcript', 'notes']);

    if (state.isRecording) {
        isRecording = true;
        updateUI();
    }

    if (state.transcript && state.transcript.length > 0) {
        transcriptLines = state.transcript;
        renderTranscript();
    }

    if (state.notes) {
        currentNotes = state.notes;
        renderNotes(currentNotes, isRecording);
        downloadSection.classList.remove('hidden');
    }

    // Check connection and status from background
    checkStatus();

    // Setup event listeners
    setupEventListeners();

    // Start periodic sync for when popup is open
    startSync();
});

function setupEventListeners() {
    // Start recording
    startBtn.addEventListener('click', async () => {
        try {
            startBtn.disabled = true;
            statusText.textContent = 'Starting...';
            statusBar.classList.remove('hidden');

            // Send message to background to start recording
            const response = await chrome.runtime.sendMessage({ type: 'START_RECORDING' });

            if (response.success) {
                isRecording = true;
                transcriptLines = [];
                currentNotes = null;
                downloadSection.classList.add('hidden');
                clearPanels();
                updateUI();
            } else {
                throw new Error(response.error || 'Failed to start recording');
            }
        } catch (error) {
            console.error('Start error:', error);
            alert('Failed to start recording: ' + error.message);
            startBtn.disabled = false;
            statusBar.classList.add('hidden');
            statusText.textContent = 'Ready';
        }
    });

    // Stop recording
    stopBtn.addEventListener('click', async () => {
        try {
            stopBtn.disabled = true;
            statusText.textContent = 'Stopping...';

            const response = await chrome.runtime.sendMessage({ type: 'STOP_RECORDING' });

            if (response.success) {
                isRecording = false;
                updateUI();

                if (response.notes) {
                    currentNotes = response.notes;
                    renderNotes(currentNotes, false);
                    downloadSection.classList.remove('hidden');
                }
            } else {
                // Even if it failed (e.g. not recording), reset UI
                console.warn('Stop warning:', response.error);
                isRecording = false;
                updateUI();
            }
        } catch (error) {
            console.error('Stop error:', error);
            // Force reset UI
            isRecording = false;
            updateUI();
        }
    });

    // Tab switching
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const targetTab = tab.dataset.tab;

            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
            document.getElementById(`${targetTab}Panel`).classList.add('active');
        });
    });

    // Download buttons
    document.getElementById('downloadTranscript').addEventListener('click', downloadTranscript);
    document.getElementById('downloadNotes').addEventListener('click', downloadNotes);

    // Settings
    document.getElementById('openSettings').addEventListener('click', (e) => {
        e.preventDefault();
        chrome.runtime.openOptionsPage();
    });

    // Listen for messages from background
    chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
        handleBackgroundMessage(message);
    });

    // Listen for storage changes (real-time sync)
    chrome.storage.onChanged.addListener((changes, areaName) => {
        if (areaName !== 'local') return;

        if (changes.transcript) {
            transcriptLines = changes.transcript.newValue || [];
            renderTranscript();
        }

        if (changes.notes && changes.notes.newValue) {
            currentNotes = changes.notes.newValue;
            renderNotes(currentNotes, isRecording);
            if (!isRecording) {
                downloadSection.classList.remove('hidden');
            }
        }
    });
}

function handleBackgroundMessage(message) {
    switch (message.type) {
        case 'TRANSCRIPT':
            addTranscriptLine(message.text, message.timestamp);
            break;

        case 'NOTES_UPDATE':
            currentNotes = message.notes;
            renderNotes(currentNotes, true);
            break;

        case 'STATUS':
            statusText.textContent = message.text;
            break;

        case 'CONNECTION_STATUS':
            isConnected = message.connected;
            updateConnectionStatus();
            break;

        case 'ERROR':
            console.error('Background error:', message.error);
            statusText.textContent = 'Error: ' + message.error;
            break;
    }
}

function addTranscriptLine(text, timestamp) {
    const line = `[${timestamp?.toFixed(1) || '0.0'}s] ${text}`;
    transcriptLines.push(line);

    // Save to storage
    chrome.storage.local.set({ transcript: transcriptLines });

    renderTranscript();
}

function renderTranscript() {
    const content = transcriptPanel.querySelector('.panel-content');

    if (transcriptLines.length === 0) {
        content.innerHTML = `
            <div class="empty-state">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                        d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                </svg>
                <p>Click "Start Recording" to begin</p>
            </div>
        `;
        return;
    }

    content.innerHTML = transcriptLines
        .map(line => `<div class="transcript-line">${escapeHtml(line)}</div>`)
        .join('');

    // Auto-scroll
    content.scrollTop = content.scrollHeight;
}

function renderNotes(notes, isLive = false) {
    const content = notesPanel.querySelector('.panel-content');

    if (!notes || !notes.summary) {
        content.innerHTML = `
            <div class="empty-state">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                        d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                <p>Notes will appear here during recording</p>
            </div>
        `;
        return;
    }

    let html = '';

    if (isLive) {
        html += `
            <div class="live-badge">
                <div class="recording-dot"></div>
                Live notes - updating every 30s
            </div>
        `;
    }

    if (notes.summary) {
        html += `
            <div class="notes-section">
                <h3>📝 Summary</h3>
                <p>${escapeHtml(notes.summary)}</p>
            </div>
        `;
    }

    if (notes.key_points?.length > 0) {
        html += `
            <div class="notes-section">
                <h3>💡 Key Points</h3>
                <ul>${notes.key_points.map(p => `<li>${escapeHtml(p)}</li>`).join('')}</ul>
            </div>
        `;
    }

    if (notes.action_items?.length > 0) {
        html += `
            <div class="notes-section">
                <h3>✅ Action Items</h3>
                <ul>${notes.action_items.map(a => `<li>${escapeHtml(a)}</li>`).join('')}</ul>
            </div>
        `;
    }

    if (notes.decisions?.length > 0) {
        html += `
            <div class="notes-section">
                <h3>⚖️ Decisions</h3>
                <ul>${notes.decisions.map(d => `<li>${escapeHtml(d)}</li>`).join('')}</ul>
            </div>
        `;
    }

    if (notes.questions?.length > 0) {
        html += `
            <div class="notes-section">
                <h3>❓ Open Questions</h3>
                <ul>${notes.questions.map(q => `<li>${escapeHtml(q)}</li>`).join('')}</ul>
            </div>
        `;
    }

    content.innerHTML = html;

    // Save to storage
    chrome.storage.local.set({ notes: notes });
}

function clearPanels() {
    transcriptPanel.querySelector('.panel-content').innerHTML = `
        <div class="empty-state">
            <p>Listening for audio...</p>
        </div>
    `;

    notesPanel.querySelector('.panel-content').innerHTML = `
        <div class="empty-state">
            <p>Notes will appear here during recording</p>
        </div>
    `;
}

function updateUI() {
    startBtn.disabled = isRecording;
    stopBtn.disabled = !isRecording;

    if (isRecording) {
        statusBar.classList.remove('hidden');
        statusText.textContent = 'Recording...';
    } else {
        statusBar.classList.add('hidden');
    }

    // Save state - ONLY update local storage if we want to default subsequent opens to this
    // But since we now check status, this is less critical/harmful
    chrome.storage.local.set({ isRecording });
}

function updateConnectionStatus() {
    const dot = connectionStatus.querySelector('.dot');

    if (isConnected) {
        dot.classList.remove('disconnected');
        dot.classList.add('connected');
        connectionText.textContent = 'Connected to API';
    } else {
        dot.classList.remove('connected');
        dot.classList.add('disconnected');
        connectionText.textContent = 'Not connected';
    }
}

async function checkStatus() {
    try {
        const response = await chrome.runtime.sendMessage({ type: 'GET_STATUS' });

        // Update local state based on source of truth (background)
        isRecording = response.isRecording;
        isConnected = response.connected;

        // Sync transcript and notes from background
        if (response.transcript && response.transcript.length > 0) {
            transcriptLines = response.transcript;
            renderTranscript();
        }

        if (response.notes) {
            currentNotes = response.notes;
            renderNotes(currentNotes, isRecording);
            if (!isRecording && currentNotes.summary) {
                downloadSection.classList.remove('hidden');
            }
        }

        updateUI();
        updateConnectionStatus();

        // If background says not recording, ensure storage is synced
        if (!isRecording) {
            chrome.storage.local.set({ isRecording: false });
        }

    } catch (error) {
        console.warn('Status check failed:', error);
        isConnected = false;
        isRecording = false; // Default to false if we can't talk to background
        updateUI();
        updateConnectionStatus();
    }
}

function startSync() {
    // Sync every 3 seconds while popup is open
    syncInterval = setInterval(async () => {
        if (isRecording) {
            await checkStatus();
        }
    }, 3000);
}

function stopSync() {
    if (syncInterval) {
        clearInterval(syncInterval);
        syncInterval = null;
    }
}

function downloadTranscript() {
    if (transcriptLines.length === 0) {
        alert('No transcript available');
        return;
    }

    const content = transcriptLines.join('\n');
    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);

    const a = document.createElement('a');
    a.href = url;
    a.download = `transcript_${formatDate()}.txt`;
    a.click();

    URL.revokeObjectURL(url);
}

function downloadNotes() {
    if (!currentNotes) {
        alert('No notes available');
        return;
    }

    let content = '# Meeting Notes\n\n';

    if (currentNotes.summary) {
        content += `## Summary\n${currentNotes.summary}\n\n`;
    }

    if (currentNotes.key_points?.length > 0) {
        content += `## Key Points\n${currentNotes.key_points.map(p => `- ${p}`).join('\n')}\n\n`;
    }

    if (currentNotes.action_items?.length > 0) {
        content += `## Action Items\n${currentNotes.action_items.map(a => `- [ ] ${a}`).join('\n')}\n\n`;
    }

    if (currentNotes.decisions?.length > 0) {
        content += `## Decisions\n${currentNotes.decisions.map(d => `- ${d}`).join('\n')}\n\n`;
    }

    if (currentNotes.questions?.length > 0) {
        content += `## Open Questions\n${currentNotes.questions.map(q => `- ${q}`).join('\n')}\n\n`;
    }

    const blob = new Blob([content], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);

    const a = document.createElement('a');
    a.href = url;
    a.download = `notes_${formatDate()}.md`;
    a.click();

    URL.revokeObjectURL(url);
}

function formatDate() {
    return new Date().toISOString().slice(0, 19).replace(/:/g, '-');
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
