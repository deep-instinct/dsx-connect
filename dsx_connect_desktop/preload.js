const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('dsxDesktop', {
  pickFolder: async () => {
    return ipcRenderer.invoke('dsx-desktop:pick-folder');
  },
  pickFile: async () => {
    return ipcRenderer.invoke('dsx-desktop:pick-file');
  },
  openExternal: async (url) => {
    return ipcRenderer.invoke('dsx-desktop:open-external', url);
  },
  restartConnector: async (uuid) => {
    return ipcRenderer.invoke('dsx-desktop:restart-connector', uuid);
  },
  startTunnel: async (uuid) => {
    return ipcRenderer.invoke('dsx-desktop:start-tunnel', uuid);
  },
});
