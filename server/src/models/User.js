import mongoose from "mongoose";
import bcrypt from "bcryptjs";

export const ROLES = ["admin", "pharmacist", "doctor", "researcher"];

const userSchema = new mongoose.Schema(
  {
    name: { type: String, required: true, trim: true },
    email: { type: String, required: true, unique: true, lowercase: true, trim: true },
    passwordHash: { type: String, required: true },
    role: { type: String, enum: ROLES, required: true },
    active: { type: Boolean, default: true },
    mfaEnabled: { type: Boolean, default: false },
    // TOTP secret, stored encrypted ("enc:v1:..." via utils/cryptoField.js). Legacy plaintext
    // values are re-encrypted on next successful use or by scripts/migrateMfaSecrets.js.
    mfaSecret: { type: String },
    // Replay protection: highest RFC 6238 time-step counter already accepted for this user.
    mfaLastUsedStep: { type: Number, default: null },
    // Per-account lockout after repeated MFA failures.
    mfaFailedAttempts: { type: Number, default: 0 },
    mfaLockedUntil: { type: Date, default: null },
  },
  { timestamps: true }
);

userSchema.methods.setPassword = async function (plain) {
  this.passwordHash = await bcrypt.hash(plain, 10);
};

userSchema.methods.checkPassword = function (plain) {
  return bcrypt.compare(plain, this.passwordHash);
};

userSchema.methods.toSafeJSON = function () {
  return {
    id: this._id,
    name: this.name,
    email: this.email,
    role: this.role,
    active: this.active,
    mfaEnabled: Boolean(this.mfaEnabled),
  };
};

export default mongoose.model("User", userSchema);
