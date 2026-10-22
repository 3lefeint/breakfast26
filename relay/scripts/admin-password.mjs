// Sets the admin password of the relay: asks for it (typed hidden, or piped in), refuses a short one, and writes the salted hash
// as the Worker secret ADMIN_PASSWORD_HASH and a new random ADMIN_TOKEN_KEY (which ends every login that is still open).
// Nothing goes to a file or to git. Arguments after `--` go to `wrangler secret put`, e.g. `-c wrangler.local.jsonc`:
//   npm run admin-password -- -c wrangler.local.jsonc
import { randomBytes } from "node:crypto";
import { spawn } from "node:child_process";
import { makeHash, PASSWORD_MIN } from "./adminHash.mjs";

function readPassword(prompt) {
  if (!process.stdin.isTTY) {
    return new Promise((resolve) => {
      let text = "";
      process.stdin.setEncoding("utf8");
      process.stdin.on("data", (d) => (text += d));
      process.stdin.on("end", () => resolve(text.replace(/\r?\n$/, "")));
    });
  }
  return new Promise((resolve) => {
    process.stdout.write(prompt);
    process.stdin.setRawMode(true);
    process.stdin.resume();
    process.stdin.setEncoding("utf8");
    let text = "";
    const onData = (ch) => {
      for (const c of ch) {
        if (c === "\u0003") { process.stdout.write("\n"); process.exit(130); }
        if (c === "\r" || c === "\n") {
          process.stdin.setRawMode(false);
          process.stdin.pause();
          process.stdin.off("data", onData);
          process.stdout.write("\n");
          return resolve(text);
        }
        text = c === "\u007f" ? text.slice(0, -1) : text + c;
      }
    };
    process.stdin.on("data", onData);
  });
}

function putSecret(name, value, args) {
  return new Promise((resolve, reject) => {
    const child = spawn("npx", ["wrangler", "secret", "put", name, ...args], { stdio: ["pipe", "inherit", "inherit"] });
    child.stdin.end(value);
    child.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`wrangler secret put ${name} failed (${code})`))));
  });
}

const args = process.argv.slice(2);
const password = await readPassword("New admin password (from your password manager, 20 or more characters are better): ");
if (password.length < PASSWORD_MIN) {
  console.error(`The password has to have at least ${PASSWORD_MIN} characters.`);
  process.exit(1);
}
await putSecret("ADMIN_PASSWORD_HASH", makeHash(password), args);
await putSecret("ADMIN_TOKEN_KEY", randomBytes(32).toString("hex"), args);
console.log("Done. Logins that were open are over, log in again with the new password.");
