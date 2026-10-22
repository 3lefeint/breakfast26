// The stored form of the admin password, `sha256$<salt hex>$<hash hex>`; src/admin.ts checks it (passwordHash / verifyPassword).
import { createHash, randomBytes } from "node:crypto";

export const PASSWORD_MIN = 12;

export function makeHash(password, saltHex = randomBytes(16).toString("hex")) {
  return `sha256$${saltHex}$${createHash("sha256").update(`${saltHex}:${password}`).digest("hex")}`;
}
