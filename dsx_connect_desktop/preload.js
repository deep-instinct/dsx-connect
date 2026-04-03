const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('dsxDesktop', {
  pickFolder: async () => {
    return ipcRenderer.invoke('dsx-desktop:pick-folder');
  },
});
