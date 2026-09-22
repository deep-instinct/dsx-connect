const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("dsxaDesktop", {
  pickFile: () => ipcRenderer.invoke("dsxa-desktop:pick-file"),
  pickFolder: () => ipcRenderer.invoke("dsxa-desktop:pick-folder"),
  loadProfiles: () => ipcRenderer.invoke("dsxa-desktop:load-profiles"),
  saveProfiles: (state) => ipcRenderer.invoke("dsxa-desktop:save-profiles", state),
  checkScanner: (profile) => ipcRenderer.invoke("dsxa-desktop:check-scanner", profile),
  scanFile: (req) => ipcRenderer.invoke("dsxa-desktop:scan-file", req),
  scanFolder: (req) => ipcRenderer.invoke("dsxa-desktop:scan-folder", req),
  scanHash: (req) => ipcRenderer.invoke("dsxa-desktop:scan-hash", req),
  onFolderProgress: (listener) => {
    const wrapped = (_event, payload) => listener(payload);
    ipcRenderer.on("dsxa-desktop:folder-progress", wrapped);
    return () => {
      ipcRenderer.removeListener("dsxa-desktop:folder-progress", wrapped);
    };
  }
});
