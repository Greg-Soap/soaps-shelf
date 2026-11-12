#!/usr/bin/env node
import { compileFiction, detectParser, listRegisteredHosts } from "./compile.mjs";

function readArg(name, fallback = undefined) {
  const idx = process.argv.indexOf(`--${name}`);
  if (idx === -1) return fallback;
  return process.argv[idx + 1];
}

function hasFlag(name) {
  return process.argv.includes(`--${name}`);
}

async function main() {
  if (hasFlag("hosts")) {
    const hosts = listRegisteredHosts();
    process.stdout.write(JSON.stringify({ count: hosts.length, hosts }, null, 2) + "\n");
    return;
  }

  const url = readArg("url");
  if (!url) {
    console.error("Usage: node src/cli.mjs --url <fiction-url> [--limit N] [--from I] [--to J] [--delay SEC]");
    console.error("       node src/cli.mjs --detect --url <fiction-url>");
    console.error("       node src/cli.mjs --hosts");
    process.exit(2);
  }

  if (hasFlag("detect")) {
    process.stdout.write(JSON.stringify(detectParser(url), null, 2) + "\n");
    return;
  }

  const result = await compileFiction({
    url,
    limit: readArg("limit"),
    chapterFrom: readArg("from", 0),
    chapterTo: readArg("to"),
    delay: readArg("delay", 0.55),
  });
  process.stdout.write(JSON.stringify(result) + "\n");
}

main().catch((err) => {
  console.error(err.stack || err.message || err);
  process.exit(1);
});
