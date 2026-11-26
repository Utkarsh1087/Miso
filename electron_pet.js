// Auto-detect and heal if running under Node or if ELECTRON_RUN_AS_NODE was inherited from VS Code / IDE
const electron = require('electron');
if (typeof electron === 'string' || !electron.app) {
  const { spawn } = require('child_process');
  const electronExe = typeof electron === 'string' ? electron : require('electron');
  const env = { ...process.env };
  delete env.ELECTRON_RUN_AS_NODE;
  const extraArgs = process.argv.slice(2).filter(arg => !arg.includes('electron_pet'));
  const child = spawn(electronExe, [__filename, ...extraArgs], {
    env,
    stdio: 'inherit',
    windowsHide: false
  });
  child.on('exit', (code) => process.exit(code || 0));
  return;
}

const { app, BrowserWindow, screen, ipcMain, shell, Tray, Menu } = electron;
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

// Ensure hardware transparency visuals for Windows DWM
app.commandLine.appendSwitch('enable-transparent-visuals');
app.commandLine.appendSwitch('disable-gpu-vsync');

let mainWindow = null;
let setupWindow = null;
let tray = null;
let currentDisplayIndex = 0;
let backendProcess = null;

const envPath = path.join(__dirname, '.env');

function startBackendServer() {
  if (backendProcess) return;

  const args = ['main.py', '--hands-free'];
  console.log('[electron] Spawning Miso Python backend engine...');

  // Use python from active virtualenv if present, otherwise system python
  const venvPythonWin = path.join(__dirname, '.venv', 'Scripts', 'python.exe');
  const pythonCmd = fs.existsSync(venvPythonWin) ? venvPythonWin : 'python';

  backendProcess = spawn(pythonCmd, args, {
    cwd: __dirname,
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
    windowsHide: true
  });

  backendProcess.stdout.on('data', (data) => {
    const text = data.toString().trim();
    if (text) console.log(`[backend] ${text}`);
  });

  backendProcess.stderr.on('data', (data) => {
    const text = data.toString().trim();
    if (text) console.log(`[backend err] ${text}`);
  });

  backendProcess.on('exit', (code) => {
    console.log(`[backend] Process exited with code ${code}`);
    backendProcess = null;
  });
}

function stopBackendServer() {
  if (backendProcess) {
    console.log('[electron] Stopping backend process...');
    try {
      backendProcess.kill();
    } catch {}
    backendProcess = null;
  }
}

function loadSavedConfig() {
  const config = { GROQ_API_KEY: '', FISH_API_KEY: '', mic: 'default', mode: 'hands-free' };
  if (fs.existsSync(envPath)) {
    const raw = fs.readFileSync(envPath, 'utf-8');
    raw.split('\n').forEach(line => {
      const match = line.match(/^([^=]+)=(.*)$/);
      if (match) {
        const k = match[1].trim();
        const v = match[2].trim();
        if (k === 'GROQ_API_KEY') config.GROQ_API_KEY = v;
        if (k === 'FISH_API_KEY') config.FISH_API_KEY = v;
      }
    });
  }
  return config;
}

function saveConfig(settings) {
  let envLines = [];
  if (fs.existsSync(envPath)) {
    envLines = fs.readFileSync(envPath, 'utf-8').split('\n');
  }

  const keysToUpdate = {
    GROQ_API_KEY: settings.GROQ_API_KEY || '',
    FISH_API_KEY: settings.FISH_API_KEY || ''
  };

  const updatedKeys = new Set();
  const newLines = envLines.map(line => {
    const match = line.match(/^([^=]+)=(.*)$/);
    if (match) {
      const k = match[1].trim();
      if (keysToUpdate[k] !== undefined) {
        updatedKeys.add(k);
        return `${k}=${keysToUpdate[k]}`;
      }
    }
    return line;
  });

  for (const [k, v] of Object.entries(keysToUpdate)) {
    if (!updatedKeys.has(k)) {
      newLines.push(`${k}=${v}`);
    }
  }

  fs.writeFileSync(envPath, newLines.join('\n').trim() + '\n', 'utf-8');
}

function createSetupWindow() {
  if (setupWindow && !setupWindow.isDestroyed()) {
    setupWindow.focus();
    return;
  }

  setupWindow = new BrowserWindow({
    width: 480,
    height: 560,
    resizable: false,
    frame: false,
    center: true,
    show: false,
    backgroundColor: '#0f0f17',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    }
  });

  setupWindow.loadFile(path.join(__dirname, 'client', 'setup.html'));
  setupWindow.once('ready-to-show', () => {
    setupWindow.show();
  });

  setupWindow.on('closed', () => {
    setupWindow = null;
  });
}

function getDisplayByIndex(index) {
  const displays = screen.getAllDisplays();
  if (index >= 0 && index < displays.length) {
    return displays[index];
  }
  return screen.getPrimaryDisplay();
}

function applyDisplayBounds(display) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const wa = display.workArea;
  mainWindow.setBounds({
    x: wa.x,
    y: wa.y,
    width: wa.width,
    height: wa.height
  });
}

function createMainWindow() {
  const displays = screen.getAllDisplays();
  const primary = screen.getPrimaryDisplay();
  currentDisplayIndex = displays.findIndex(d => d.id === primary.id);
  if (currentDisplayIndex === -1) currentDisplayIndex = 0;

  const currentDisplay = displays[currentDisplayIndex];
  const { x, y, width, height } = currentDisplay.workArea;

  mainWindow = new BrowserWindow({
    width: width,
    height: height,
    x: x,
    y: y,
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    hasShadow: false,
    resizable: false,
    skipTaskbar: true,
    backgroundColor: '#00000000',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    }
  });

  // Default to pass-through with mouse forwarding enabled so empty transparent space is 100% clickable
  mainWindow.setIgnoreMouseEvents(true, { forward: true });

  // Keep pet visible across Windows virtual desktops
  if (typeof mainWindow.setVisibleOnAllWorkspaces === 'function') {
    mainWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  }

  // Handle dynamic click-through switching from renderer
  ipcMain.on('set-ignore-mouse-events', (event, ignore, options) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    if (win && !win.isDestroyed()) {
      win.setIgnoreMouseEvents(ignore, options || { forward: true });
    }
  });

  function reattachWindow(targetDisplay) {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    applyDisplayBounds(targetDisplay);
    // On Windows DWM, hide + show pulls top-level frameless window onto the user's active Virtual Desktop
    mainWindow.hide();
    setTimeout(() => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.show();
        mainWindow.setAlwaysOnTop(true);
        mainWindow.setIgnoreMouseEvents(true, { forward: true });
        mainWindow.webContents.send('display-changed', {
          index: currentDisplayIndex,
          total: screen.getAllDisplays().length,
          workArea: targetDisplay.workArea
        });
      }
    }, 60);
  }

  // Multi-Monitor switching: jumps smoothly to secondary or next display
  ipcMain.on('switch-display', (event, targetIndex) => {
    const allDisplays = screen.getAllDisplays();
    if (typeof targetIndex === 'number' && targetIndex >= 0 && targetIndex < allDisplays.length) {
      currentDisplayIndex = targetIndex;
    } else if (allDisplays.length > 1) {
      currentDisplayIndex = (currentDisplayIndex + 1) % allDisplays.length;
    }
    const targetDisplay = allDisplays[currentDisplayIndex] || screen.getPrimaryDisplay();
    reattachWindow(targetDisplay);
  });

  // Hop to active monitor where senpai's mouse cursor is currently working
  ipcMain.on('move-to-cursor-display', () => {
    const cursorPoint = screen.getCursorScreenPoint();
    const targetDisplay = screen.getDisplayNearestPoint(cursorPoint);
    const allDisplays = screen.getAllDisplays();
    const targetIndex = allDisplays.findIndex(d => d.id === targetDisplay.id);
    if (targetIndex !== -1) {
      currentDisplayIndex = targetIndex;
    }
    reattachWindow(targetDisplay);
  });

  // Query display info (used by frontend to adapt boundaries)
  ipcMain.handle('get-display-info', () => {
    const allDisplays = screen.getAllDisplays();
    return {
      currentIndex: currentDisplayIndex,
      total: allDisplays.length,
      displays: allDisplays.map((d, i) => ({
        index: i,
        id: d.id,
        isPrimary: d.id === screen.getPrimaryDisplay().id,
        workArea: d.workArea
      }))
    };
  });

  // Screen hotplug detection: if monitor plugged/unplugged, keep Riko safely grounded
  const handleDisplaysChanged = () => {
    const allDisplays = screen.getAllDisplays();
    if (currentDisplayIndex >= allDisplays.length) {
      currentDisplayIndex = 0;
    }
    const active = allDisplays[currentDisplayIndex] || screen.getPrimaryDisplay();
    applyDisplayBounds(active);
  };

  screen.on('display-added', handleDisplaysChanged);
  screen.on('display-removed', handleDisplaysChanged);
  screen.on('display-metrics-changed', handleDisplaysChanged);

  // Auto-reconnect if Electron launches before Python server is fully listening
  mainWindow.webContents.on('did-fail-load', (event, errorCode, errorDescription, validatedURL) => {
    console.log(`[electron] Waiting for Miso server at ${validatedURL} (${errorDescription})... Retrying in 1.5s`);
    setTimeout(() => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.loadURL('http://127.0.0.1:8080/?transparent=true');
      }
    }, 1500);
  });

  mainWindow.webContents.on('did-finish-load', () => {
    console.log('[electron] Connected to Miso 3D Pet viewport.');
  });

  mainWindow.webContents.on('console-message', (event, ...args) => {
    const level = (event && typeof event.level === 'number') ? event.level : args[0];
    const message = (event && typeof event.message === 'string') ? event.message : args[1];
    if (message && message.includes('Electron Security Warning')) return;
    if (level === 3) {
      console.log(`[renderer error] ${message}`);
    }
  });

  mainWindow.loadURL('http://127.0.0.1:8080/?transparent=true');

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ── Setup Wizard & Settings IPC Handlers ──
ipcMain.handle('load-settings', () => {
  return loadSavedConfig();
});

ipcMain.handle('save-settings-and-launch', (event, settings) => {
  try {
    saveConfig(settings);
    if (setupWindow && !setupWindow.isDestroyed()) {
      setupWindow.close();
    }
    startBackendServer();
    if (!mainWindow || mainWindow.isDestroyed()) {
      createMainWindow();
    } else {
      mainWindow.show();
    }
    return { success: true };
  } catch (e) {
    return { error: e.message };
  }
});

ipcMain.on('close-setup', () => {
  if (setupWindow && !setupWindow.isDestroyed()) {
    setupWindow.close();
  }
});

ipcMain.on('open-external', (event, url) => {
  if (url && (url.startsWith('https://') || url.startsWith('http://'))) {
    shell.openExternal(url);
  }
});

function createTray() {
  if (tray) return;
  // Create simple system tray context menu
  const iconPath = path.join(__dirname, 'client', 'favicon.ico');
  try {
    tray = new Tray(fs.existsSync(iconPath) ? iconPath : path.join(__dirname, 'docs', 'banner-dark.png'));
  } catch (e) {
    // If icon missing, skip tray gracefully
    return;
  }
  const contextMenu = Menu.buildFromTemplate([
    { label: '✨ Miso Desktop Companion', enabled: false },
    { type: 'separator' },
    { label: '⚙ Settings / API Keys', click: () => createSetupWindow() },
    { label: '🎯 Recenter on Screen', click: () => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        const primary = screen.getPrimaryDisplay();
        applyDisplayBounds(primary);
      }
    }},
    { type: 'separator' },
    { label: '❌ Exit Miso', click: () => {
      app.isQuitting = true;
      app.quit();
    }}
  ]);
  tray.setToolTip('Miso 3D Companion');
  tray.setContextMenu(contextMenu);
}

function initApp() {
  createTray();
  const cfg = loadSavedConfig();
  // If first launch without configured API keys, show setup window first!
  if (!cfg.GROQ_API_KEY || !cfg.FISH_API_KEY) {
    createSetupWindow();
  } else {
    startBackendServer();
    createMainWindow();
  }
}

app.whenReady().then(initApp);

app.on('will-quit', () => {
  stopBackendServer();
});

app.on('window-all-closed', () => {
  stopBackendServer();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
