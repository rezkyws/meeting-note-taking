/**
 * AI Meeting Note Taker - Options Page Script
 * 
 * Handles settings storage and API connection testing.
 */

const apiUrlInput = document.getElementById('apiUrl');
const apiKeyInput = document.getElementById('apiKey');
const saveBtn = document.getElementById('saveBtn');
const testBtn = document.getElementById('testBtn');
const statusDiv = document.getElementById('status');

// Load saved settings
document.addEventListener('DOMContentLoaded', async () => {
    const settings = await chrome.storage.sync.get(['apiUrl', 'apiKey']);

    apiUrlInput.value = settings.apiUrl || 'http://localhost:8001';
    apiKeyInput.value = settings.apiKey || '';
});

// Save settings
saveBtn.addEventListener('click', async () => {
    const apiUrl = apiUrlInput.value.trim();
    const apiKey = apiKeyInput.value.trim();

    if (!apiUrl) {
        showStatus('Please enter an API URL', 'error');
        return;
    }

    if (!apiKey) {
        showStatus('Please enter an API key', 'error');
        return;
    }

    await chrome.storage.sync.set({ apiUrl, apiKey });

    showStatus('Settings saved successfully!', 'success');
});

// Test connection
testBtn.addEventListener('click', async () => {
    const apiUrl = apiUrlInput.value.trim();
    const apiKey = apiKeyInput.value.trim();

    if (!apiUrl || !apiKey) {
        showStatus('Please enter both API URL and API key', 'error');
        return;
    }

    showStatus('Testing connection...', 'success');

    try {
        const response = await fetch(`${apiUrl}/api/v1/auth/validate`, {
            method: 'POST',
            headers: {
                'X-API-Key': apiKey,
                'Content-Type': 'application/json',
            },
        });

        if (response.ok) {
            const data = await response.json();
            showStatus(
                `✅ Connected! Tier: ${data.tier}, Features: ${data.features.join(', ')}`,
                'success'
            );
        } else if (response.status === 401) {
            showStatus('❌ Invalid API key', 'error');
        } else if (response.status === 429) {
            showStatus('⚠️ Rate limited. Try again in a moment.', 'error');
        } else {
            showStatus(`❌ Server error: ${response.status}`, 'error');
        }
    } catch (error) {
        if (error.message.includes('Failed to fetch')) {
            showStatus('❌ Cannot connect to server. Is it running?', 'error');
        } else {
            showStatus(`❌ Error: ${error.message}`, 'error');
        }
    }
});

function showStatus(message, type) {
    statusDiv.textContent = message;
    statusDiv.className = `status ${type}`;
}
