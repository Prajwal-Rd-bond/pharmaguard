import test, { describe } from "node:test";
import assert from "node:assert";
import { encryptField, decryptField, isEncrypted } from "../src/utils/cryptoField.js";
import { generateTOTPSecret, generateTOTP, verifyTOTPToken } from "../src/utils/totp.js";
import { parseClinicalDocument } from "../src/utils/documentParser.js";
import { tracingMiddleware } from "../src/middleware/tracing.js";

describe("Field-Level PHI Encryption (AES-256-GCM)", () => {
  test("successfully encrypts plaintext and decrypts back to original text", () => {
    const sensitivePhi = "Patient John Doe (DOB 1974-05-12, MRN #99104) experienced severe anaphylaxis";
    const encrypted = encryptField(sensitivePhi);

    assert.ok(isEncrypted(encrypted), "Encrypted string should have 'enc:v1:' prefix");
    assert.notStrictEqual(encrypted, sensitivePhi);

    const decrypted = decryptField(encrypted);
    assert.strictEqual(decrypted, sensitivePhi);
  });

  test("handles idempotent re-encryption and legacy plaintext transparently", () => {
    const plaintext = "Report with no PHI";
    const encOnce = encryptField(plaintext);
    const encTwice = encryptField(encOnce);
    assert.strictEqual(encOnce, encTwice, "Re-encrypting should be idempotent");

    const plainLegacy = "legacy unencrypted database text";
    assert.strictEqual(decryptField(plainLegacy), plainLegacy, "Unencrypted text passes through decryptField");
  });

  test("detects data tampering via AES-GCM authentication tag verification", () => {
    const text = "Confidential clinical record";
    const encrypted = encryptField(text);
    const parts = encrypted.split(":");

    // Tamper with the ciphertext byte
    const tamperedCipher = parts[4].slice(0, -2) + (parts[4].endsWith("0") ? "1" : "0");
    const tamperedRecord = `${parts[0]}:${parts[1]}:${parts[2]}:${parts[3]}:${tamperedCipher}`;

    assert.throws(() => {
      decryptField(tamperedRecord);
    }, "Tampered ciphertext should fail authentication tag check");
  });
});

describe("Multi-Factor Authentication (RFC 6238 TOTP)", () => {
  test("generates valid secret and matches generated OTP passcode", () => {
    const { secret, otpauthUrl } = generateTOTPSecret("doctor@hospital.org");
    assert.ok(secret.length >= 16);
    assert.ok(otpauthUrl.includes("otpauth://totp/"));

    const currentToken = generateTOTP(secret);
    assert.strictEqual(currentToken.length, 6);
    assert.match(currentToken, /^\d{6}$/);

    const isValid = verifyTOTPToken(secret, currentToken);
    assert.strictEqual(isValid, true, "Generated OTP should verify successfully");
  });

  test("rejects invalid or malformed tokens", () => {
    const { secret } = generateTOTPSecret("pharmacist@safety.org");
    assert.strictEqual(verifyTOTPToken(secret, "000000"), false);
    assert.strictEqual(verifyTOTPToken(secret, "123"), false);
    assert.strictEqual(verifyTOTPToken(secret, "abcdef"), false);
  });
});

describe("Multi-Format Clinical Document Ingestion Parser", () => {
  test("extracts text from plain text and json files", () => {
    const textBuf = Buffer.from("Patient developed hives after ibuprofen intake.");
    assert.strictEqual(parseClinicalDocument(textBuf, "report.txt"), "Patient developed hives after ibuprofen intake.");

    const jsonBuf = Buffer.from(JSON.stringify({ rawText: "Structured JSON ADR report" }));
    assert.strictEqual(parseClinicalDocument(jsonBuf, "case.json"), "Structured JSON ADR report");
  });

  test("extracts text from simulated PDF stream operators", () => {
    // Construct PDF snippet with text operator: (Patient suffered rash) Tj
    const pdfSim = "%PDF-1.4\nstream\nBT\n/F1 12 Tf\n(Patient suffered acute rash) Tj\nET\nendstream";
    const extracted = parseClinicalDocument(Buffer.from(pdfSim), "discharge.pdf");
    assert.ok(extracted.includes("Patient suffered acute rash"));
  });

  test("extracts text from simulated Word document XML tags", () => {
    const docxSim = '<w:p><w:r><w:t>Patient experienced severe dyspnoea</w:t></w:r></w:p>';
    const extracted = parseClinicalDocument(Buffer.from(docxSim), "clinical_note.docx");
    assert.ok(extracted.includes("Patient experienced severe dyspnoea"));
  });
});

describe("Distributed Tracing Middleware", () => {
  test("attaches x-trace-id header and propagates to request object", () => {
    const req = { headers: {} };
    const resHeaders = {};
    const res = {
      setHeader: (k, v) => {
        resHeaders[k.toLowerCase()] = v;
      },
    };

    let nextCalled = false;
    tracingMiddleware(req, res, () => {
      nextCalled = true;
    });

    assert.strictEqual(nextCalled, true);
    assert.ok(req.traceId);
    assert.strictEqual(resHeaders["x-trace-id"], req.traceId);
  });
});

