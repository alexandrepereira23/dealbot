// Proxy somente do laboratório: prova NEXT_PUBLIC_API_URL=/api em uma origem.
import http from "node:http";

const server = http.createServer((req, res) => {
  if (req.url === "/__lab/parar-proxy" && req.method === "POST" && req.headers["x-lab-controle"] === "sintetico") {
    res.end("encerrando"); server.close(); return;
  }
  const api = req.url.startsWith("/api/") || req.url.startsWith("/media/") || req.url.startsWith("/__lab/");
  const port = api ? 54328 : 54325;
  const destino = http.request({ hostname: "127.0.0.1", port, method: req.method, path: req.url,
    headers: { ...req.headers, host: `127.0.0.1:${port}` } }, resposta => {
    res.writeHead(resposta.statusCode, resposta.headers); resposta.pipe(res);
  });
  destino.on("error", () => { res.statusCode = 502; res.end("laboratorio-indisponivel"); });
  req.pipe(destino);
});
server.listen(54326, "127.0.0.1", () => console.log("proxy-laboratorio:54326"));
