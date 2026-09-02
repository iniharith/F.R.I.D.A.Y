const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const path = require('path');
const { spawn, exec } = require('child_process');
const fs = require('fs');
const crypto = require('crypto');
const os = require('os');
const QRCode = require('qrcode');

app.disableHardwareAcceleration();

let mainWindow;
let fridayProcess = null;
let isServerRunning = false;
let readinessTimer = null;
let previousCpuTimes = null;

const FRIDAY_PORT = 8000;
const FRIDAY_URL = `http://127.0.0.1:${FRIDAY_PORT}`;

function getFridayRoot() {
  const devPath = path.join(__dirname, '..', '..');
  const portableDir = process.env.PORTABLE_EXECUTABLE_DIR || path.dirname(app.getPath('exe'));
  const companionPath = path.resolve(portableDir, '..');
  const prodPath = process.resourcesPath
    ? path.join(process.resourcesPath, 'friday')
    : devPath;
  for (const candidate of [prodPath, companionPath, devPath]) {
    if (fs.existsSync(path.join(candidate, 'core')) && fs.existsSync(path.join(candidate, 'models'))) {
      return candidate;
    }
  }
  return devPath;
}

function getSettingsPath() {
  return path.join(app.getPath('userData'), 'launcher-settings.json');
}

function getLanAddress() {
  const addresses = [];
  for (const entries of Object.values(os.networkInterfaces())) {
    for (const entry of entries || []) {
      if (!entry.internal && (entry.family === 'IPv4' || entry.family === 4)) {
        addresses.push(entry.address);
      }
    }
  }
  return addresses.find((address) => /^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)/.test(address))
    || addresses[0]
    || '127.0.0.1';
}

function defaultSettings() {
  return {
    wakeWord: 'friday', ttsMode: 'local', micDefaultOn: true,
    host: '0.0.0.0', port: FRIDAY_PORT, autoStart: true,
    reasoningMode: 'local', cloudModel: 'z-ai/glm-5.3-flash',
    pairingToken: crypto.randomBytes(18).toString('base64url'),
  };
}

function readSettings() {
  try {
    const saved = JSON.parse(fs.readFileSync(getSettingsPath(), 'utf-8'));
    const settings = { ...defaultSettings(), ...saved };
    if (settings.reasoningMode !== 'openrouter') settings.reasoningMode = 'local';
    if (!settings.cloudModel) settings.cloudModel = 'z-ai/glm-5.3-flash';
    if (!saved.pairingToken) {
      fs.writeFileSync(getSettingsPath(), JSON.stringify(settings, null, 2));
    }
    return settings;
  } catch {
    const settings = defaultSettings();
    fs.mkdirSync(path.dirname(getSettingsPath()), { recursive: true });
    fs.writeFileSync(getSettingsPath(), JSON.stringify(settings, null, 2));
    return settings;
  }
}

function getPythonPath() {
  const root = getFridayRoot();
  const venvPython = path.join(root, '.venv', 'Scripts', 'python.exe');
  if (fs.existsSync(venvPython)) return venvPython;

  const bundledPython = path.join(root, 'py312', 'python.exe');
  if (fs.existsSync(bundledPython)) return bundledPython;

  return 'python';
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 900,
    minHeight: 700,
    frame: false,
    titleBarStyle: 'hidden',
    backgroundColor: '#04080f',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      webviewTag: false,
    },
    icon: path.join(__dirname, 'assets', 'friday-logo.png'),
  });

  mainWindow.loadFile(path.join(__dirname, 'index.html'));
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  mainWindow.webContents.on('will-navigate', (event) => event.preventDefault());

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

function startFridayBackend() {
  if (isServerRunning || fridayProcess) return;

  const root = getFridayRoot();
  const python = getPythonPath();
  if (!fs.existsSync(path.join(root, 'models'))) {
    sendLog('error', 'FRIDAY kit not found. Keep this EXE in dist-launcher beside the friday-kit contents.');
    sendStatus('error');
    return;
  }

  const env = { ...process.env };
  env.FRIDAY_ROOT = root;
  const settings = readSettings();
  env.FRIDAY_DATA_DIR = path.join(app.getPath('userData'), 'data');
  env.FRIDAY_HOST = settings.host || '127.0.0.1';
  env.FRIDAY_PORT = String(settings.port || FRIDAY_PORT);
  env.FRIDAY_PAIRING_TOKEN = settings.pairingToken;
  env.FRIDAY_NO_BROWSER = '1';
  env.PYTHONUNBUFFERED = '1';
  env.FRIDAY_WAKE_WORD = settings.wakeWord || 'friday';
  env.FRIDAY_TTS_MODE = settings.ttsMode || 'local';
  env.FRIDAY_TTS_LOCAL_VOICE = settings.localVoice || 'bf_isabella';
  env.FRIDAY_TTS_LANGUAGE = settings.language || 'en-gb';
  env.FRIDAY_MIC_DEFAULT_ON = String(settings.micDefaultOn !== false);
  env.FRIDAY_WAKE_WINDOW = String(settings.wakeWindow || 8);
  env.FRIDAY_MIC_MIN_RMS = String(settings.minRms || 280);
  env.FRIDAY_VAD_THRESHOLD = String(settings.vadThreshold || 0.5);
  env.FRIDAY_MAX_NEW_TOKENS = String(settings.maxTokens || 512);
  env.FRIDAY_CONTEXT_TURNS = String(settings.contextTurns || 10);
  env.FRIDAY_MEMORY_FACTS = String(settings.memFacts || 6);
  env.FRIDAY_MEMORY_EPISODES = String(settings.memEpisodes || 2);
  env.FRIDAY_GUARDIAN_CPU = String(settings.cpuThreshold || 85);
  env.FRIDAY_GUARDIAN_RAM = String(settings.ramThreshold || 90);
  env.FRIDAY_GUARDIAN_TEMP = String(settings.gpuThreshold || 85);
  env.FRIDAY_GUARDIAN_INTERVAL = String(settings.guardianInterval || 30);
  env.FRIDAY_REASONING_MODE = settings.reasoningMode === 'openrouter' ? 'openrouter' : 'local';
  env.FRIDAY_OPENROUTER_MODEL = settings.cloudModel || 'z-ai/glm-5.3-flash';

  sendStatus('starting');

  fridayProcess = spawn(python, ['-u', '-m', 'core.main'], {
    cwd: root,
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });

  fridayProcess.stdout.on('data', (data) => {
    const text = data.toString().trim();
    if (text) {
      sendLog('info', text);
    }
  });

  fridayProcess.stderr.on('data', (data) => {
    const text = data.toString().trim();
    if (text) sendLog('warn', text);
  });

  fridayProcess.on('error', (err) => {
    sendLog('error', `Failed to start Friday: ${err.message}`);
    sendStatus('error');
  });

  fridayProcess.on('exit', (code) => {
    if (readinessTimer) clearInterval(readinessTimer);
    readinessTimer = null;
    isServerRunning = false;
    sendLog('info', `Friday exited with code ${code}`);
    sendStatus('stopped');
    fridayProcess = null;
  });

  let attempts = 0;
  readinessTimer = setInterval(async () => {
    attempts += 1;
    try {
      const response = await fetch(`http://127.0.0.1:${settings.port || FRIDAY_PORT}/health`);
      if (response.ok) {
        const health = await response.json();
        if (health.model_state === 'failed') {
          sendLog('error', `Local model failed: ${health.model_error || 'unknown error'}`);
          clearInterval(readinessTimer);
          readinessTimer = null;
          sendStatus('error');
          return;
        }
        if (health.model_state !== 'ready') return;
        clearInterval(readinessTimer);
        readinessTimer = null;
        isServerRunning = true;
        sendStatus('ready');
      }
    } catch {}
    if (attempts >= 120 && readinessTimer) {
      clearInterval(readinessTimer);
      readinessTimer = null;
      sendStatus('error');
    }
  }, 500);
}

function stopFridayBackend() {
  if (fridayProcess) {
    const processToStop = fridayProcess;
    processToStop.kill('SIGTERM');
    setTimeout(() => {
      if (processToStop.exitCode === null) processToStop.kill('SIGKILL');
    }, 3000);
    isServerRunning = false;
    sendStatus('stopped');
  }
}

function sendLog(level, message) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('log-message', { level, message, timestamp: Date.now() });
  }
}

function sendStatus(status) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('server-status', status);
  }
}

ipcMain.on('window-minimize', () => mainWindow?.minimize());
ipcMain.on('window-maximize', () => {
  if (mainWindow?.isMaximized()) mainWindow.unmaximize();
  else mainWindow?.maximize();
});
ipcMain.on('window-close', () => mainWindow?.close());

ipcMain.handle('get-settings', () => {
  return readSettings();
});

ipcMain.handle('get-pairing-info', async () => {
  const settings = readSettings();
  const host = getLanAddress();
  const port = Number(settings.port) || FRIDAY_PORT;
  const token = settings.pairingToken;
  const uri = `friday://pair?host=${encodeURIComponent(host)}&port=${port}&token=${encodeURIComponent(token)}`;
  const qrDataUrl = await QRCode.toDataURL(uri, {
    errorCorrectionLevel: 'M',
    margin: 1,
    width: 220,
    color: { dark: '#071017', light: '#E8F6FF' },
  });
  return { host, port, token, uri, qrDataUrl };
});

ipcMain.handle('save-settings', (event, settings) => {
  const settingsPath = getSettingsPath();
  fs.mkdirSync(path.dirname(settingsPath), { recursive: true });
  const persisted = { ...readSettings(), ...settings };
  fs.writeFileSync(settingsPath, JSON.stringify(persisted, null, 2));
  return true;
});

ipcMain.handle('refresh-pairing-token', async () => {
  const settingsPath = getSettingsPath();
  fs.mkdirSync(path.dirname(settingsPath), { recursive: true });
  const current = readSettings();
  current.pairingToken = crypto.randomBytes(18).toString('base64url');
  fs.writeFileSync(settingsPath, JSON.stringify(current, null, 2));
  const host = getLanAddress();
  const port = Number(current.port) || FRIDAY_PORT;
  const uri = `friday://pair?host=${encodeURIComponent(host)}&port=${port}&token=${encodeURIComponent(current.pairingToken)}`;
  const qrDataUrl = await QRCode.toDataURL(uri, {
    errorCorrectionLevel: 'M',
    margin: 1,
    width: 220,
    color: { dark: '#071017', light: '#E8F6FF' },
  });
  return { host, port, token: current.pairingToken, uri, qrDataUrl };
});

ipcMain.on('start-friday', () => startFridayBackend());
ipcMain.on('stop-friday', () => stopFridayBackend());
ipcMain.on('open-friday-hud', () => {
  const settings = readSettings();
  shell.openExternal(`http://127.0.0.1:${settings.port || FRIDAY_PORT}`);
});
ipcMain.on('open-folder', (event, folder) => {
  const root = getFridayRoot();
  shell.openPath(path.join(root, folder));
});

ipcMain.handle('get-system-info', () => {
  const os = require('os');
  const current = os.cpus().map(cpu => ({ ...cpu.times }));
  let cpuUsage = 0;
  if (previousCpuTimes) {
    let idle = 0;
    let total = 0;
    current.forEach((times, index) => {
      const before = previousCpuTimes[index];
      const idleDelta = times.idle - before.idle;
      const totalDelta = Object.values(times).reduce((sum, value) => sum + value, 0)
        - Object.values(before).reduce((sum, value) => sum + value, 0);
      idle += idleDelta;
      total += totalDelta;
    });
    cpuUsage = total > 0 ? Math.round((1 - idle / total) * 100) : 0;
  }
  previousCpuTimes = current;
  return {
    platform: os.platform(),
    arch: os.arch(),
    cpus: os.cpus().length,
    totalMemory: (os.totalmem() / (1024 ** 3)).toFixed(1),
    freeMemory: (os.freemem() / (1024 ** 3)).toFixed(1),
    uptime: (os.uptime() / 3600).toFixed(1),
    hostname: os.hostname(),
    cpuUsage,
    cpuModel: os.cpus()[0]?.model || 'Unknown CPU',
  };
});

app.whenReady().then(createWindow);
app.on('window-all-closed', () => {
  stopFridayBackend();
  app.quit();
});
app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
