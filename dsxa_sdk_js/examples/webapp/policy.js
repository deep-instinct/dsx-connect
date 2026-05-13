const EXECUTABLE_FILE_TYPES = new Set([
  "PEFileType",
  "PE32FileType",
  "PE64FileType",
  "ELF32FileType",
  "ELF64FileType",
  "MachoFATFileType",
  "Macho32FileType",
  "Macho64FileType",
]);

export function classifyScan(response) {
  const fileType = response?.fileInfo?.fileType || response?.file_info?.file_type || "";
  if (EXECUTABLE_FILE_TYPES.has(fileType)) {
    return {
      accepted: false,
      bucket: "rejected",
      tone: "policy",
      headline: `File type not allowed by policy [${fileType}]`,
    };
  }

  const verdict = String(response?.verdict || "");
  if (verdict === "Benign") {
    return {
      accepted: true,
      bucket: "accepted",
      tone: "accepted",
      headline: "Accepted into loan application",
    };
  }
  if (verdict === "Malicious") {
    return {
      accepted: false,
      bucket: "rejected",
      tone: "rejected",
      headline: "Blocked as malicious",
    };
  }
  if (verdict === "Non Compliant") {
    return {
      accepted: false,
      bucket: "rejected",
      tone: "rejected",
      headline: "Blocked as non-compliant",
    };
  }
  return {
    accepted: false,
    bucket: "review",
    tone: "review",
    headline: "Not accepted automatically",
  };
}
