#!/usr/bin/env node
import http from "node:http";
import { compileFiction, detectParser, listRegisteredHosts } from "./compile.mjs";

const PORT = Number(process.env.WTE_PORT || 8791);
const HOST = process.env.WTE_HOST || "127.0.0.1";

function sendJson(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(payload),
  });
  res.end(payload);
}

async function readJson(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  if (!chunks.length) return {};
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url || "/", `http://${HOST}:${PORT}`);

    if (req.method === "GET" && url.pathname === "/health") {
      return sendJson(res, 200, { ok: true, hosts: listRegisteredHosts().length });
    }

    if (req.method === "GET" && url.pathname === "/hosts") {
      const hosts = listRegisteredHosts();
      return sendJson(res, 200, { count: hosts.length, hosts });
    }

    if (req.method === "POST" && url.pathname === "/detect") {
      const body = await readJson(req);
      return sendJson(res, 200, detectParser(body.url || ""));
    }

    if (req.method === "POST" && url.pathname === "/compile") {
      const body = await readJson(req);
      const result = await compileFiction(body);
      return sendJson(res, 200, result);
    }

    sendJson(res, 404, { detail: "Not found" });
  } catch (err) {
    sendJson(res, 500, { detail: err.message || String(err) });
  }
});

server.listen(PORT, HOST, () => {
  // Warm parser registry so first compile is faster.
  try {
    const count = listRegisteredHosts().length;
    console.log(`WebToEpub runner on http://${HOST}:${PORT} (${count} hosts)`);
  } catch (err) {
    console.error("Failed to warm parsers:", err);
    console.log(`WebToEpub runner on http://${HOST}:${PORT}`);
  }
});
