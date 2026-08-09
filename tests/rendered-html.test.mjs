import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the SpaceLens interface without local paths", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>SpaceLens — 磁盘空间分析器<\/title>/i);
  assert.match(html, /磁盘占用矩形树图/);
  assert.match(html, /重复文件/);
  assert.doesNotMatch(html, /[A-Z]:\\Users\\|\/Users\/[^/]+\//i);
});

test("local scanner remains private by default", async () => {
  const [server, gitignore, readme] = await Promise.all([
    readFile(new URL("../local_server.py", import.meta.url), "utf8"),
    readFile(new URL("../.gitignore", import.meta.url), "utf8"),
    readFile(new URL("../README.md", import.meta.url), "utf8"),
  ]);

  assert.match(server, /ThreadingHTTPServer\(\("127\.0\.0\.1", port\), Handler\)/);
  assert.match(gitignore, /^\/saved_scans\/$/m);
  assert.match(gitignore, /^\.env\*$/m);
  assert.match(readme, /不会主动上传扫描结果或硬盘信息/);
});
