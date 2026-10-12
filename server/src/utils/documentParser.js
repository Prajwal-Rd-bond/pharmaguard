/**
 * PharmaGuard Multi-Format Clinical Document Ingestion Parser
 * Extracts clinical narrative and structured observations from:
 * - Plaintext (.txt, .md)
 * - JSON and CSV adverse event export formats
 * - Portable Document Format (.pdf)
 * - Office Open XML Word Documents (.docx)
 */

import zlib from "zlib";

/**
 * Extracts plain clinical text from a PDF buffer by decoding text streams and string operators.
 */
export function extractTextFromPdfBuffer(buffer) {
  if (!buffer || buffer.length === 0) return "";
  const content = buffer.toString("binary");
  const extractedLines = [];

  // Match uncompressed PDF text operators: (Text) Tj, [(Text)] TJ
  const tjRegex = /\(([^)]+)\)\s*Tj/g;
  let match;
  while ((match = tjRegex.exec(content)) !== null) {
    if (match[1]) extractedLines.push(match[1]);
  }

  const tjArrayRegex = /\[([^\]]+)\]\s*TJ/g;
  while ((match = tjArrayRegex.exec(content)) !== null) {
    const rawItems = match[1];
    const itemStrings = [];
    const itemMatchRegex = /\(([^)]+)\)/g;
    let im;
    while ((im = itemMatchRegex.exec(rawItems)) !== null) {
      itemStrings.push(im[1]);
    }
    if (itemStrings.length > 0) {
      extractedLines.push(itemStrings.join(" "));
    }
  }

  // If uncompressed stream extraction found text, return it
  if (extractedLines.length > 0) {
    return cleanExtractedText(extractedLines.join(" "));
  }

  // Scan for compressed deflate FlateDecode streams
  const streamRegex = /stream\r?\n([\s\S]*?)\r?\nendstream/g;
  let sm;
  while ((sm = streamRegex.exec(content)) !== null) {
    try {
      const streamBytes = Buffer.from(sm[1], "binary");
      const decompressed = zlib.inflateSync(streamBytes).toString("utf8");
      while ((match = tjRegex.exec(decompressed)) !== null) {
        if (match[1]) extractedLines.push(match[1]);
      }
    } catch {
      // Ignore non-deflated or encrypted streams
    }
  }

  if (extractedLines.length > 0) {
    return cleanExtractedText(extractedLines.join(" "));
  }

  // Fallback: extract ASCII printable strings
  const asciiChunks = content.match(/[\x20-\x7E]{4,}/g) || [];
  return cleanExtractedText(asciiChunks.join(" "));
}

/**
 * Extracts clinical text from a DOCX buffer by reading document XML tags (<w:t>).
 */
export function extractTextFromDocxBuffer(buffer) {
  if (!buffer || buffer.length === 0) return "";
  const content = buffer.toString("binary");

  // In DOCX zip files, XML text blocks are enclosed within <w:t>...</w:t> or <w:t xml:space="preserve">
  const wtRegex = /<w:t[^>]*>([^<]+)<\/w:t>/g;
  const words = [];
  let match;

  while ((match = wtRegex.exec(content)) !== null) {
    if (match[1]) words.push(match[1]);
  }

  if (words.length > 0) {
    return cleanExtractedText(words.join(" "));
  }

  // Fallback: extract contiguous text chunks
  const asciiChunks = content.match(/[A-Za-z0-9\s.,;:\-()]{4,}/g) || [];
  return cleanExtractedText(asciiChunks.join(" "));
}

/**
 * Cleans extracted text by standardizing whitespace and removing binary control characters.
 */
function cleanExtractedText(text) {
  return text
    .replace(/\\r/g, " ")
    .replace(/\\n/g, "\n")
    .replace(/\\t/g, " ")
    .replace(/[^\x20-\x7E\n]/g, " ")
    .replace(/[ ]{2,}/g, " ")
    .trim();
}

/**
 * Main ingestion entry point: inspects filename or mimetype and parses text from uploaded buffer.
 */
export function parseClinicalDocument(buffer, filename = "", mimetype = "") {
  if (!buffer || buffer.length === 0) return "";

  const cleanFilename = filename.toLowerCase();
  const cleanMime = (mimetype || "").toLowerCase();

  if (cleanFilename.endsWith(".pdf") || cleanMime.includes("pdf")) {
    return extractTextFromPdfBuffer(buffer);
  }

  if (
    cleanFilename.endsWith(".docx") ||
    cleanMime.includes("wordprocessingml") ||
    cleanMime.includes("officedocument")
  ) {
    return extractTextFromDocxBuffer(buffer);
  }

  if (cleanFilename.endsWith(".json") || cleanMime.includes("json")) {
    try {
      const parsed = JSON.parse(buffer.toString("utf8"));
      if (typeof parsed === "string") return parsed;
      if (parsed.rawText || parsed.text || parsed.narrative) {
        return parsed.rawText || parsed.text || parsed.narrative;
      }
      return JSON.stringify(parsed, null, 2);
    } catch {
      return buffer.toString("utf8");
    }
  }

  // Default plaintext (.txt, .md, .csv)
  return buffer.toString("utf8").trim();
}

