const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("dsxGateway", {
  loadSettings: () => ipcRenderer.invoke("gateway:load-settings"),
  saveSettings: (settings) => ipcRenderer.invoke("gateway:save-settings", settings),
  pickFiles: () => ipcRenderer.invoke("gateway:pick-files"),
  listDestinations: (settings) => ipcRenderer.invoke("gateway:list-destinations", settings),
  submitTransfer: (request) => ipcRenderer.invoke("gateway:submit-transfer", request),
  getTransferStatus: (request) => ipcRenderer.invoke("gateway:get-transfer-status", request),
  getDsxaItems: (request) => ipcRenderer.invoke("gateway:get-dsxa-items", request),
  getDsxaJob: (request) => ipcRenderer.invoke("gateway:get-dsxa-job", request)
});
