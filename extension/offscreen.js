/**
 * AI Meeting Note Taker - Offscreen Document Script
 * 
 * Handles actual audio capture and encoding.
 * Runs in an offscreen document to access MediaRecorder API.
 */

let mediaRecorder = null;
let mediaStream = null;
let audioContext = null;
let recordingInterval = null;

// Listen for messages from background
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.target !== 'offscreen') {
        return;
    }

    switch (message.type) {
        case 'START_CAPTURE':
            startCapture(message.streamId)
                .then(() => sendResponse({ success: true }))
                .catch(error => sendResponse({ success: false, error: error.message }));
            return true;

        case 'STOP_CAPTURE':
            stopCapture();
            sendResponse({ success: true });
            break;
    }
});

async function startCapture(streamId) {
    try {
        // Get media stream from stream ID
        mediaStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                mandatory: {
                    chromeMediaSource: 'tab',
                    chromeMediaSourceId: streamId,
                },
            },
            video: false,
        });

        // 1. PLAYBACK: Route audio to destination so user hears it
        audioContext = new AudioContext();
        const source = audioContext.createMediaStreamSource(mediaStream);
        source.connect(audioContext.destination);

        // 2. HANDLE AUDIO CONTEXT SUSPENSION
        // AudioContext can be suspended when tab loses focus
        // Set up interval to check and resume if needed
        setInterval(() => {
            if (audioContext && audioContext.state === 'suspended') {
                audioContext.resume().then(() => {
                    console.log('AudioContext resumed');
                }).catch(e => console.warn('AudioContext resume failed:', e));
            }
        }, 1000);

        // 3. RECORDING: Record in chunks using start/stop loop for headers
        startRecordingParams();

        console.log('Audio capture started');

    } catch (error) {
        console.error('Capture error:', error);
        throw error;
    }
}

function startRecordingParams() {
    if (!mediaStream) return;

    // Use MediaRecorder to capture a specific chunk
    const options = {
        mimeType: 'audio/webm;codecs=opus',
        audioBitsPerSecond: 64000,
    };

    const recorder = new MediaRecorder(mediaStream, options);
    let chunks = [];

    recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
            chunks.push(event.data);
        }
    };

    recorder.onstop = async () => {
        if (chunks.length > 0) {
            const blob = new Blob(chunks, { type: 'audio/webm' });
            // Process and send the chunk
            const base64 = await blobToBase64(blob);

            chrome.runtime.sendMessage({
                type: 'AUDIO_DATA',
                target: 'background',
                data: base64,
                format: 'webm',
            });
        }
    };

    // Start recording
    recorder.start();

    // Stop and restart loop
    mediaRecorder = recorder; // Keep reference to stop globally if needed

    // Re-trigger every 3 seconds
    // Note: We create a NEW recorder each time to ensure file headers are reset
    // This solves the "Invalid data" issue on server
    recordingInterval = setTimeout(() => {
        if (mediaStream) {
            recorder.stop();
            startRecordingParams(); // Recursive call for next chunk
        }
    }, 3000);
}

function stopCapture() {
    // Clear loop
    if (recordingInterval) {
        clearTimeout(recordingInterval);
        recordingInterval = null;
    }

    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop();
    }

    // Stop all tracks
    if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
        mediaStream = null;
    }

    // Close AudioContext
    if (audioContext) {
        audioContext.close();
        audioContext = null;
    }

    mediaRecorder = null;

    console.log('Audio capture stopped');
}

function blobToBase64(blob) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onloadend = () => {
            // Remove data URL prefix
            const base64 = reader.result.split(',')[1];
            resolve(base64);
        };
        reader.onerror = reject;
        reader.readAsDataURL(blob);
    });
}
