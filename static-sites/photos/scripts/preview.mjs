import * as esbuild from "esbuild";
import { createServer } from "node:http";
import { watch } from "node:fs";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  rmSync,
  statSync,
} from "node:fs";
import { extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const dist = join(root, "dist");
const samples = join(root, "sample-photos");
const port = 8765;
const liveReload = `<script>
  new EventSource("/__reload").onmessage = () => location.reload();
</script>
`;

const mime = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".webp": "image/webp",
  ".gif": "image/gif",
  ".map": "application/json",
};

const clients = new Set();
let photosBody = Buffer.from("[]");
let reloadTimer;

function notify() {
  clearTimeout(reloadTimer);
  reloadTimer = setTimeout(() => {
    for (const res of clients) {
      res.write("data: reload\n\n");
    }
    console.log("reload");
  }, 80);
}

function copy(from, to) {
  mkdirSync(join(to, ".."), { recursive: true });
  copyFileSync(from, to);
}

function loadPhotos() {
  const photosDir = join(dist, "photos");
  mkdirSync(photosDir, { recursive: true });
  const manifest = JSON.parse(readFileSync(join(samples, "manifest.json"), "utf8"));
  const photos = [];
  for (const entry of manifest.photos) {
    const src = join(samples, entry.file);
    if (!existsSync(src)) {
      throw new Error(`Missing sample photo: ${src}`);
    }
    copy(src, join(photosDir, entry.file));
    photos.push({
      url: `/photos/${entry.file}`,
      name: entry.file,
      title: entry.title,
      description: entry.description ?? "",
      tags: entry.tags ?? [],
      prints: [
        { id: 1, label: "Poster · 12×18", price: "28.00" },
        { id: 2, label: "Poster · 24×36", price: "48.00" },
        { id: 3, label: "Framed poster · 12×18", price: "72.00" },
        { id: 4, label: "Framed poster · 24×36", price: "128.00" },
      ],
      lastModified: "2026-11-04T18:00:00Z",
    });
  }
  photosBody = Buffer.from(JSON.stringify({ photos }));
}

function copyStatic() {
  mkdirSync(join(dist, "assets"), { recursive: true });
  copy(join(root, "index.html"), join(dist, "index.html"));
  copy(join(root, "error.html"), join(dist, "error.html"));
  copy(join(root, "contact.html"), join(dist, "contact.html"));
  copy(join(root, "cropped_final.jpg"), join(dist, "cropped_final.jpg"));
  copy(join(root, "src/styles.css"), join(dist, "assets/styles.css"));
  loadPhotos();
}

function ignored(rel) {
  return (
    rel.startsWith("dist/") ||
    rel.startsWith("node_modules/") ||
    rel.startsWith("scripts/") ||
    rel.startsWith(".")
  );
}

function onSourceChange(filename) {
  if (!filename) {
    return;
  }
  const rel = filename.split("\\").join("/");
  if (ignored(rel)) {
    return;
  }
  if (/\.(ts|tsx)$/.test(rel)) {
    return;
  }
  try {
    copyStatic();
    notify();
    console.log(`updated ${rel}`);
  } catch (err) {
    console.error(err);
  }
}

function inject(html) {
  if (html.includes("</body>")) {
    return html.replace("</body>", `${liveReload}</body>`);
  }
  return html + liveReload;
}

function send(res, status, type, body) {
  res.writeHead(status, {
    "Content-Type": type,
    "Content-Length": Buffer.byteLength(body),
    "Cache-Control": "no-store",
  });
  res.end(body);
}

function serveFile(req, res, urlPath) {
  let rel = decodeURIComponent(urlPath.split("?")[0]);
  if (rel === "/") {
    rel = "/index.html";
  }
  const filePath = resolve(dist, `.${rel}`);
  if (!filePath.startsWith(dist) || !existsSync(filePath) || statSync(filePath).isDirectory()) {
    const fallback = join(dist, "error.html");
    send(res, 404, "text/html; charset=utf-8", inject(readFileSync(fallback, "utf8")));
    return;
  }
  const type = mime[extname(filePath).toLowerCase()] ?? "application/octet-stream";
  if (type.startsWith("text/html")) {
    send(res, 200, type, inject(readFileSync(filePath, "utf8")));
    return;
  }
  send(res, 200, type, readFileSync(filePath));
}

mkdirSync(dist, { recursive: true });
if (existsSync(join(dist, "photos"))) {
  rmSync(join(dist, "photos"), { recursive: true });
}
copyStatic();

const ctx = await esbuild.context({
  entryPoints: [join(root, "src/main.ts")],
  bundle: true,
  sourcemap: true,
  outfile: join(dist, "assets/main.js"),
  plugins: [
    {
      name: "reload",
      setup(build) {
        build.onEnd((result) => {
          if (result.errors.length === 0) {
            notify();
          } else {
            console.error(result.errors);
          }
        });
      },
    },
  ],
});

await ctx.rebuild();
await ctx.watch();
watch(root, { recursive: true }, (_event, filename) => onSourceChange(filename));

const server = createServer((req, res) => {
  const urlPath = req.url ?? "/";
  if (urlPath.split("?")[0] === "/__reload") {
    res.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-store",
      Connection: "keep-alive",
    });
    res.write("\n");
    clients.add(res);
    req.on("close", () => clients.delete(res));
    return;
  }
  if (urlPath.split("?")[0] === "/api/photos") {
    send(res, 200, "application/json; charset=utf-8", photosBody);
    return;
  }
  if (urlPath.split("?")[0] === "/api/checkout") {
    req.resume();
    req.on("end", () => {
      send(
        res,
        503,
        "application/json; charset=utf-8",
        JSON.stringify({ error: "Checkout is not configured yet." }),
      );
    });
    return;
  }
  serveFile(req, res, urlPath);
});

server.listen(port, "127.0.0.1", () => {
  console.log(`http://127.0.0.1:${port}`);
});

function shutdown() {
  void ctx.dispose();
  server.close();
  process.exit(0);
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
