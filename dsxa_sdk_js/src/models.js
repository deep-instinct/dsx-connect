function maybeObject(value) {
  return value && typeof value === "object" ? value : {};
}

export class VerdictDetails {
  constructor(data = {}) {
    const src = maybeObject(data);
    this.eventDescription = src.event_description ?? null;
    this.reason = src.reason ?? null;
    this.threatType = src.threat_type ?? null;
  }

  toJSON() {
    return {
      event_description: this.eventDescription,
      reason: this.reason,
      threat_type: this.threatType,
    };
  }
}

export class FileInfo {
  constructor(data = {}) {
    const src = maybeObject(data);
    this.fileType = src.file_type ?? null;
    this.fileSizeInBytes = src.file_size_in_bytes ?? null;
    this.fileHash = src.file_hash ?? null;
    this.containerHash = src.container_hash ?? null;
    this.additionalOfficeData = src.additional_office_data ?? null;
  }

  toJSON() {
    return {
      file_type: this.fileType,
      file_size_in_bytes: this.fileSizeInBytes,
      file_hash: this.fileHash,
      container_hash: this.containerHash,
      additional_office_data: this.additionalOfficeData,
    };
  }
}

export class ScanResponse {
  constructor(data = {}) {
    const src = maybeObject(data);
    this.scanGuid = src.scan_guid ?? "";
    this.verdict = src.verdict ?? "";
    this.verdictDetails = new VerdictDetails(src.verdict_details);
    this.fileInfo = src.file_info ? new FileInfo(src.file_info) : null;
    this.protectedEntity = src.protected_entity ?? null;
    this.scanDurationInMicroseconds = src.scan_duration_in_microseconds ?? null;
    this.containerFilesScanned = src.container_files_scanned ?? null;
    this.containerFilesScannedSize = src.container_files_scanned_size ?? null;
    this.customMetadata = src["X-Custom-Metadata"] ?? src.x_custom_metadata ?? null;
    this.lastUpdateTime = src.last_update_time ?? null;
  }

  static fromJson(data = {}) {
    return new ScanResponse(data);
  }

  get isPending() {
    return String(this.verdict).toLowerCase() === "scanning";
  }

  toJSON() {
    return {
      scan_guid: this.scanGuid,
      verdict: this.verdict,
      verdict_details: this.verdictDetails.toJSON(),
      file_info: this.fileInfo ? this.fileInfo.toJSON() : null,
      protected_entity: this.protectedEntity,
      scan_duration_in_microseconds: this.scanDurationInMicroseconds,
      container_files_scanned: this.containerFilesScanned,
      container_files_scanned_size: this.containerFilesScannedSize,
      "X-Custom-Metadata": this.customMetadata,
      last_update_time: this.lastUpdateTime,
    };
  }
}

export class ScanByPathResponse extends ScanResponse {
  static fromJson(data = {}) {
    return new ScanByPathResponse(data);
  }
}

export class HashScanResponse extends ScanResponse {
  static fromJson(data = {}) {
    return new HashScanResponse(data);
  }
}
