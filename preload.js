const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  setIgnoreMouseEvents: (ignore, options) => {
    ipcRenderer.send('set-ignore-mouse-events', ignore, options);
  },
  switchDisplay: (targetIndex) => {
    ipcRenderer.send('switch-display', targetIndex);
  },
  moveToCursorDisplay: () => {
    ipcRenderer.send('move-to-cursor-display');
  },
  getDisplayInfo: () => {
    return ipcRenderer.invoke('get-display-info');
  },
  onDisplayChanged: (callback) => {
    ipcRenderer.on('display-changed', (event, data) => callback(data));
  },
  loadSettings: () => {
    return ipcRenderer.invoke('load-settings');
  },
  saveSettingsAndLaunch: (settings) => {
    return ipcRenderer.invoke('save-settings-and-launch', settings);
  },
  closeSetup: () => {
    ipcRenderer.send('close-setup');
  },
  openExternal: (url) => {
    ipcRenderer.send('open-external', url);
  }
});
