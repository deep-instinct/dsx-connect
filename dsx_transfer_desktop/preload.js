const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("dsxTransferDesktop", {
  pickFolder: (purpose) => ipcRenderer.invoke("dsx-transfer-desktop:pick-folder", purpose),
  loadSettings: () => ipcRenderer.invoke("dsx-transfer-desktop:load-settings"),
  saveSettings: (settings) => ipcRenderer.invoke("dsx-transfer-desktop:save-settings", settings),
  runTransfer: (request) => ipcRenderer.invoke("dsx-transfer-desktop:run-transfer", request),
  openPath: (targetPath) => ipcRenderer.invoke("dsx-transfer-desktop:open-path", targetPath),
  onTransferProgress: (listener) => {
    const wrapped = (_event, payload) => listener(payload);
    ipcRenderer.on("dsx-transfer-desktop:transfer-progress", wrapped);
    return () => {
      ipcRenderer.removeListener("dsx-transfer-desktop:transfer-progress", wrapped);
    };
  },
  onThemeChanged: (listener) => {
    const wrapped = (_event, payload) => listener(payload);
    ipcRenderer.on("dsx-transfer-desktop:theme-changed", wrapped);
    return () => {
      ipcRenderer.removeListener("dsx-transfer-desktop:theme-changed", wrapped);
    };
  }
});
