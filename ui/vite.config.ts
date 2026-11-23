import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

const SERVER = process.env.WHAAT_SERVER ?? "http://127.0.0.1:1111";

/** The server knows where its state folder is on this system; asking it keeps the rule in one place. */
function stateDir(): string {
  return execFileSync("uv", ["run", "--quiet", "whaat", "state-dir"], {
    cwd: resolve(import.meta.dirname, "../server"),
    encoding: "utf8",
  }).trim();
}

function serverToken(): string {
  if (process.env.WHAAT_TOKEN) return process.env.WHAAT_TOKEN;
  try {
    return readFileSync(join(process.env.WHAAT_STATE_DIR ?? stateDir(), "token"), "utf8").trim();
  } catch {
    return "";
  }
}

const TOKEN_PLACEHOLDER = "%WHAAT_TOKEN%";

// The build keeps the placeholder and the Python server fills it in when it serves index.html, so one build works
// behind any state dir; the dev server fills it from the token file itself.
function devToken(): Plugin {
  return {
    name: "whaat-dev-token",
    apply: "serve",
    transformIndexHtml: (html) => html.replace(TOKEN_PLACEHOLDER, serverToken()),
  };
}

export default defineConfig(({ command }) => ({
  base: command === "build" ? "/ui/" : "/",
  plugins: [tanstackRouter({ target: "react", autoCodeSplitting: true }), react(), tailwindcss(), devToken()],
  resolve: { alias: { "@": resolve(import.meta.dirname, "src") } },
  server: { port: 5173, strictPort: true, proxy: { "/api": { target: SERVER } } },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
}));
