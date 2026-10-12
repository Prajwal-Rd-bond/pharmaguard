import crypto from "crypto";

// Fallback master key derived via SHA-256 if PHI_ENCRYPTION_KEY is not explicitly configured
const DEFAULT_SALT = "pharmaguard-phi-salt-2026";
function getEncryptionKey() {
  const secret = process.env.PHI_ENCRYPTION_KEY || process.env.JWT_SECRET || "pharmaguard-default-phi-secret-key-32b";
  return crypto.scryptSync(secret, DEFAULT_SALT, 32);
}

const ALGORITHM = "aes-256-gcm";
const IV_LENGTH = 12; // 96 bits recommended for GCM

/**
 * Encrypts a sensitive clinical PHI field using AES-256-GCM.
 * Output format: enc:v1:<iv_hex>:<tag_hex>:<ciphertext_hex>
 */
export function encryptField(plaintext) {
  if (plaintext === null || plaintext === undefined) return plaintext;
  const str = String(plaintext);
  if (str.startsWith("enc:v1:")) return str; // Already encrypted

  const key = getEncryptionKey();
  const iv = crypto.randomBytes(IV_LENGTH);
  const cipher = crypto.createCipheriv(ALGORITHM, key, iv);

  let encrypted = cipher.update(str, "utf8", "hex");
  encrypted += cipher.final("hex");
  const authTag = cipher.getAuthTag().toString("hex");

  return `enc:v1:${iv.toString("hex")}:${authTag}:${encrypted}`;
}

/**
 * Decrypts an encrypted PHI field.
 * Safely handles unencrypted plaintext for backwards compatibility.
 */
export function decryptField(encryptedText) {
  if (!encryptedText || typeof encryptedText !== "string") return encryptedText;
  if (!encryptedText.startsWith("enc:v1:")) return encryptedText; // Unencrypted legacy field

  const parts = encryptedText.split(":");
  if (parts.length !== 5) {
    throw new Error("Invalid encrypted field format");
  }

  const iv = Buffer.from(parts[2], "hex");
  const authTag = Buffer.from(parts[3], "hex");
  const ciphertext = parts[4];

  const key = getEncryptionKey();
  const decipher = crypto.createDecipheriv(ALGORITHM, key, iv);
  decipher.setAuthTag(authTag);

  let decrypted = decipher.update(ciphertext, "hex", "utf8");
  decrypted += decipher.final("utf8");

  return decrypted;
}

/**
 * Checks whether a given string is currently encrypted with AES-256-GCM
 */
export function isEncrypted(val) {
  return typeof val === "string" && val.startsWith("enc:v1:");
}

