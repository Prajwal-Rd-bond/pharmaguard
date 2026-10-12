import crypto from "crypto";

const BASE32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

function base32Encode(buffer) {
  let bits = 0;
  let value = 0;
  let output = "";

  for (let i = 0; i < buffer.length; i++) {
    value = (value << 8) | buffer[i];
    bits += 8;

    while (bits >= 5) {
      output += BASE32_ALPHABET[(value >>> (bits - 5)) & 31];
      bits -= 5;
    }
  }

  if (bits > 0) {
    output += BASE32_ALPHABET[(value << (5 - bits)) & 31];
  }

  return output;
}

function base32Decode(base32Str) {
  const cleanStr = base32Str.toUpperCase().replace(/=+$/, "");
  let bits = 0;
  let value = 0;
  const bytes = [];

  for (let i = 0; i < cleanStr.length; i++) {
    const val = BASE32_ALPHABET.indexOf(cleanStr[i]);
    if (val === -1) continue;

    value = (value << 5) | val;
    bits += 5;

    if (bits >= 8) {
      bytes.push((value >>> (bits - 8)) & 255);
      bits -= 8;
    }
  }

  return Buffer.from(bytes);
}

/**
 * Generates a standard RFC 6238 TOTP 6-digit passcode for a secret and timestamp.
 */
export function generateTOTP(secretBase32, timeStepSeconds = 30, timestampMs = Date.now()) {
  const key = base32Decode(secretBase32);
  const counter = Math.floor(timestampMs / 1000 / timeStepSeconds);

  const counterBuf = Buffer.alloc(8);
  counterBuf.writeBigInt64BE(BigInt(counter));

  const hmac = crypto.createHmac("sha1", key);
  hmac.update(counterBuf);
  const digest = hmac.digest();

  // Dynamic truncation (RFC 4226 section 5.4)
  const offset = digest[digest.length - 1] & 0x0f;
  const binary =
    ((digest[offset] & 0x7f) << 24) |
    ((digest[offset + 1] & 0xff) << 16) |
    ((digest[offset + 2] & 0xff) << 8) |
    (digest[offset + 3] & 0xff);

  const otp = binary % 1000000;
  return otp.toString().padStart(6, "0");
}

/**
 * Verifies a 6-digit TOTP token against a secret with clock drift tolerance.
 */
export function verifyTOTPToken(secretBase32, token, window = 1, timeStepSeconds = 30) {
  if (!secretBase32 || !token) return false;
  const cleanToken = String(token).trim();
  if (cleanToken.length !== 6) return false;

  const nowMs = Date.now();
  for (let step = -window; step <= window; step++) {
    const testTime = nowMs + step * timeStepSeconds * 1000;
    const generated = generateTOTP(secretBase32, timeStepSeconds, testTime);
    if (crypto.timingSafeEqual(Buffer.from(cleanToken), Buffer.from(generated))) {
      return true;
    }
  }
  return false;
}

/**
 * Generates a new random Base32 TOTP secret and standard otpauth:// provisioning URL.
 */
export function generateTOTPSecret(accountName = "user@pharmaguard.local", issuer = "PharmaGuard Safety") {
  const randomBytes = crypto.randomBytes(20);
  const secretBase32 = base32Encode(randomBytes);
  const encodedIssuer = encodeURIComponent(issuer);
  const encodedAccount = encodeURIComponent(accountName);
  const otpauthUrl = `otpauth://totp/${encodedIssuer}:${encodedAccount}?secret=${secretBase32}&issuer=${encodedIssuer}&algorithm=SHA1&digits=6&period=30`;

  return {
    secret: secretBase32,
    otpauthUrl,
  };
}

