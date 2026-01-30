/**
 * AI Meeting Note Taker - Background Service Worker
 * 
 * Handles audio capture coordination, WebSocket connection to API,
 * and message relay between popup and API server.
 * 
 * Note: All sensitive operations (transcription, notes) happen on the API server.
 */

// State
let isRecording = false;
let ws = null;
let apiKey = null;
let apiUrl = 'http://localhost:8001';
let transcriptLines = [];
let currentNotes = null;

// Initialize
chrome.runtime.onInstalled.addListener(async () => {
    console.log('AI Meeting Note Taker extension installed');

    // Load settings
    const settings = await chrome.storage.sync.get(['apiKey', 'apiUrl']);
    apiKey = settings.apiKey || 'ai-noter-demo-key-2024';
    apiUrl = settings.apiUrl || 'http://localhost:8001';
});

// Load settings on startup
chrome.storage.sync.get(['apiKey', 'apiUrl']).then(settings => {
    apiKey = settings.apiKey || 'ai-noter-demo-key-2024';
    apiUrl = settings.apiUrl || 'http://localhost:8001';
});

// Listen for messages from popup
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    handleMessage(message, sender, sendResponse);
    return true; // Keep channel open for async response
});

async function handleMessage(message, sender, sendResponse) {
    try {
        switch (message.type) {
            case 'START_RECORDING':
                const startResult = await startRecording();
                sendResponse(startResult);
                break;

            case 'STOP_RECORDING':
                const stopResult = await stopRecording();
                sendResponse(stopResult);
                break;

            case 'CHECK_CONNECTION':
                const isConnected = ws && ws.readyState === WebSocket.OPEN;
                sendResponse({ connected: isConnected });
                break;

            case 'GET_STATUS':
                sendResponse({
                    isRecording,
                    connected: ws && ws.readyState === WebSocket.OPEN,
                    transcript: transcriptLines,
                    notes: currentNotes,
                });
                break;

            default:
                sendResponse({ error: 'Unknown message type' });
        }
    } catch (error) {
        console.error('Message handler error:', error);
        sendResponse({ success: false, error: error.message });
    }
}

async function startRecording() {
    if (isRecording) {
        return { success: false, error: 'Already recording' };
    }

    try {
        // Get current tab
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

        if (!tab) {
            return { success: false, error: 'No active tab' };
        }

        // Connect to API WebSocket
        const connected = await connectWebSocket();
        if (!connected) {
            return { success: false, error: 'Failed to connect to API server' };
        }

        // Create offscreen document for audio capture
        await setupOffscreenDocument();

        // Start tab capture
        const streamId = await chrome.tabCapture.getMediaStreamId({
            targetTabId: tab.id,
        });

        // Send stream ID to offscreen document
        await chrome.runtime.sendMessage({
            type: 'START_CAPTURE',
            target: 'offscreen',
            streamId: streamId,
        });

        isRecording = true;

        // Clear previous session data
        transcriptLines = [];
        currentNotes = null;
        chrome.storage.local.set({
            transcript: [],
            notes: null,
            isRecording: true
        });

        // Notify popup
        broadcastToPopup({ type: 'STATUS', text: 'Recording...' });

        return { success: true };

    } catch (error) {
        console.error('Start recording error:', error);
        return { success: false, error: error.message };
    }
}

async function stopRecording() {
    if (!isRecording) {
        return { success: false, error: 'Not recording' };
    }

    try {
        // Stop capture in offscreen document
        await chrome.runtime.sendMessage({
            type: 'STOP_CAPTURE',
            target: 'offscreen',
        });

        // Request final notes from WebSocket
        let finalNotes = null;

        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'stop' }));

            // Wait for final notes (with timeout)
            finalNotes = await new Promise((resolve) => {
                const timeout = setTimeout(() => resolve(null), 10000);

                const handler = (event) => {
                    const data = JSON.parse(event.data);
                    if (data.type === 'final_notes') {
                        clearTimeout(timeout);
                        ws.removeEventListener('message', handler);
                        resolve(data);
                    }
                };

                ws.addEventListener('message', handler);
            });
        }

        // Close WebSocket
        if (ws) {
            ws.close();
            ws = null;
        }

        // Close offscreen document
        await closeOffscreenDocument();

        isRecording = false;

        broadcastToPopup({ type: 'STATUS', text: 'Recording stopped' });
        broadcastToPopup({ type: 'CONNECTION_STATUS', connected: false });

        return {
            success: true,
            notes: finalNotes ? {
                summary: finalNotes.summary,
                key_points: finalNotes.key_points,
                action_items: finalNotes.action_items,
                decisions: finalNotes.decisions,
                questions: finalNotes.questions,
            } : null,
        };

    } catch (error) {
        console.error('Stop recording error:', error);
        isRecording = false;
        return { success: false, error: error.message };
    }
}

async function connectWebSocket() {
    return new Promise((resolve) => {
        try {
            const wsUrl = apiUrl.replace('http://', 'ws://').replace('https://', 'wss://');
            ws = new WebSocket(`${wsUrl}/api/v1/stream`);

            ws.onopen = () => {
                console.log('WebSocket connected');

                // Send auth message
                ws.send(JSON.stringify({
                    type: 'auth',
                    api_key: apiKey,
                }));
            };

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                handleWebSocketMessage(data, resolve);
            };

            ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                broadcastToPopup({ type: 'ERROR', error: 'WebSocket connection failed' });
                resolve(false);
            };

            ws.onclose = () => {
                console.log('WebSocket closed');
                broadcastToPopup({ type: 'CONNECTION_STATUS', connected: false });
            };

            // Timeout after 10 seconds
            setTimeout(() => {
                if (ws.readyState !== WebSocket.OPEN) {
                    resolve(false);
                }
            }, 10000);

        } catch (error) {
            console.error('WebSocket connection error:', error);
            resolve(false);
        }
    });
}

let wsAuthResolved = false;

function handleWebSocketMessage(data, authResolver) {
    switch (data.type) {
        case 'auth_success':
            console.log('API authentication successful');
            broadcastToPopup({ type: 'CONNECTION_STATUS', connected: true });
            if (!wsAuthResolved) {
                wsAuthResolved = true;
                authResolver(true);
            }
            break;

        case 'error':
            console.error('API error:', data.message);
            broadcastToPopup({ type: 'ERROR', error: data.message });
            if (!wsAuthResolved && data.message.includes('API key')) {
                wsAuthResolved = true;
                authResolver(false);
            }
            break;

        case 'transcript':
            // Store transcript in memory and persistent storage
            const line = `[${data.start?.toFixed(1) || '0.0'}s] ${data.text}`;
            transcriptLines.push(line);
            chrome.storage.local.set({ transcript: transcriptLines });

            broadcastToPopup({
                type: 'TRANSCRIPT',
                text: data.text,
                timestamp: data.start,
            });
            break;

        case 'notes':
            // Store notes in memory and persistent storage
            currentNotes = {
                summary: data.summary,
                key_points: data.key_points,
                action_items: data.action_items,
                decisions: data.decisions,
                questions: data.questions,
            };
            chrome.storage.local.set({ notes: currentNotes });

            broadcastToPopup({
                type: 'NOTES_UPDATE',
                notes: currentNotes,
            });
            break;

        case 'pong':
            // Heartbeat response
            break;
    }
}

// Receive audio data from offscreen document
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'AUDIO_DATA' && message.target === 'background') {
        // Forward to WebSocket
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                type: 'audio',
                data: message.data,
                format: message.format || 'webm',
            }));
        }
        sendResponse({ received: true });
    }
    return true;
});

async function setupOffscreenDocument() {
    const existingContexts = await chrome.runtime.getContexts({
        contextTypes: ['OFFSCREEN_DOCUMENT'],
    });

    if (existingContexts.length > 0) {
        return; // Already exists
    }

    await chrome.offscreen.createDocument({
        url: 'offscreen.html',
        reasons: ['USER_MEDIA'],
        justification: 'Recording tab audio for transcription',
    });
}

async function closeOffscreenDocument() {
    const existingContexts = await chrome.runtime.getContexts({
        contextTypes: ['OFFSCREEN_DOCUMENT'],
    });

    if (existingContexts.length > 0) {
        await chrome.offscreen.closeDocument();
    }
}

function broadcastToPopup(message) {
    chrome.runtime.sendMessage(message).catch(() => {
        // Popup might be closed, ignore error
    });
}

// Heartbeat to keep WebSocket alive
setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }));
    }
}, 30000);
