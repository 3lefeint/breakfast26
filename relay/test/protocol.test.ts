import { describe, expect, it } from "vitest";
import examples from "../protocol-tests/messages.json";
import { validateClientFrame, validateServerFrame } from "../src/protocol";

describe("protocol examples shared with the Python client", () => {
  for (const { valid, frame } of examples.client) {
    it(`client frame ${JSON.stringify(frame).slice(0, 70)} is ${valid ? "valid" : "refused"}`, () => {
      expect(validateClientFrame(frame) === null).toBe(valid);
    });
  }
  for (const { valid, frame } of examples.server) {
    it(`server frame ${JSON.stringify(frame).slice(0, 70)} is ${valid ? "valid" : "refused"}`, () => {
      expect(validateServerFrame(frame) === null).toBe(valid);
    });
  }
});
