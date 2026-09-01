const { contextBridge, ipcRenderer } = require('electron');

const sendChannels = new Set([
  'window-minimize',
  'window-maximize',
  'window-close',
  'start-friday',
  'stop-friday',
  'open-friday-hud',
  'open-folder',
]);
const invokeChannels = new Set(['get-settings', 'save-settings', 'get-system-info']);
const receiveChannels = new Set(['log-message', 'server-status']);

contextBridge.exposeInMainWorld('friday', {
  send(channel, ...args) {
    if (sendChannels.has(channel)) ipcRenderer.send(channel, ...args);
  },
  invoke(channel, ...args) {
    if (!invokeChannels.has(channel)) return Promise.reject(new Error('IPC channel blocked'));
    return ipcRenderer.invoke(channel, ...args);
  },
  on(channel, callback) {
    if (receiveChannels.has(channel)) {
      ipcRenderer.on(channel, (_event, ...args) => callback({}, ...args));
    }
  },
});
