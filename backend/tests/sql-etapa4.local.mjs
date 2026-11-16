// Chamado SOMENTE no ramo PostgreSQL real do runner etapa 3, após suas guardas
// de banco local vazio/descartável e os 47 grupos históricos. Não lê .env.
// RPCs/locks/arquivos/model/service reais; Storage legado é falso explícito.
// As fixtures ficam no banco e no temporário para inspeção, sem varrer finais.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { criarLimpezaModel } from "../src/models/limpeza.model.js";
import { criarMidiaLocalModel } from "../src/models/midia-local.model.js";
import { criarExecutarLimpeza } from "../src/services/limpeza.service.js";

const WEBP = Buffer.from("UklGRiQAAABXRUJQVlA4IBgAAAAwAQCdASoBAAEAAUAmJaQAA3AA/v02aAA=", "base64");
const ORIGEM = "https://projeto.invalid";
const sqlTexto = (valor) => `'${valor.replaceAll("'", "''")}'`;

export async function validarEtapa4Concorrente(h) {
  const { db, evento, produto, identidade, registrar, enriquecerSQL,
    buscar, contar, disputar, ok } = h;
  let sequencia = 0;
  const novaUrl = (destino = "local") => {
    const chave = (++sequencia).toString(16).padStart(32, "0");
    return destino === "local" ? `/media/${chave}.webp`
      : `${ORIGEM}/storage/v1/object/public/produtos/${chave}.jpg`;
  };
  const novoCard = async () => {
    const e = { ...evento(-104000 - ++sequencia, 1), enriquecer: true };
    return { e, r: await registrar(e, produto(), identidade(null)) };
  };
  const foto = (id, url) => `select * from public.oferta_foto(${id},${sqlTexto(url)})`;
  const reservar = (url) => `select * from public.midia_reservar_remocao(${sqlTexto(url)})`;
  const remover = (id) => `select * from public.oferta_remover(${id})`;
  const estadoMidia = async (url) => (await db.rows(`select * from public.oferta_midias where url=${sqlTexto(url)}`))[0];
  const pins = (a, b) => db.rows(`select canal_id,msg_id,pin,confirmado_em,decisao_hash,
    identidade_inicial,observacao from public.oferta_eventos
    where canal_id in (${a.e.canal_id},${b.e.canal_id}) order by canal_id`);
  const par = async () => {
    const a = await novoCard(); const b = await novoCard();
    const i = identidade("a", { loja: "sintetica", variante: `etapa4_${++sequencia}` });
    await db.rows(enriquecerSQL(a.e, i));
    return { a, b, i };
  };

  for (const destino of ["local", "supabase"]) {
    for (const reservaPrimeiro of [true, false]) {
      const { r } = await novoCard(); const url = novaUrl(destino);
      const [[primeira], [segunda]] = reservaPrimeiro
        ? await disputar(reservar(url), foto(r.id, url))
        : await disputar(foto(r.id, url), reservar(url));
      if (reservaPrimeiro) {
        assert.equal(primeira.permitido, true);
        assert.equal(segunda.status, "remocao_reservada");
        assert.equal((await buscar(r.id)).foto_url, null);
        await db.rows(`select * from public.midia_confirmar_remocao(${sqlTexto(url)})`);
        assert.equal((await db.rows(foto(r.id, url)))[0].status, "remocao_reservada");
        assert.equal((await estadoMidia(url)).estado, "removida");
      } else {
        assert.equal(primeira.status, "atualizada");
        assert.equal(segunda.permitido, false);
        assert.equal((await buscar(r.id)).foto_url, url);
        assert.equal(await estadoMidia(url), undefined);
      }
      ok(`etapa4 ${destino}: ${reservaPrimeiro ? "reserva→vínculo" : "vínculo→reserva"}, duas sessões/barreira real e tombstone preservado`);
    }

    for (const fusaoPrimeiro of [true, false]) {
      const { a, b, i } = await par(); const url = novaUrl(destino);
      await db.rows(foto(b.r.id, url));
      const antes = await pins(a, b);
      const [[primeira], [segunda]] = fusaoPrimeiro
        ? await disputar(enriquecerSQL(b.e, i), reservar(url))
        : await disputar(reservar(url), enriquecerSQL(b.e, i));
      assert.equal((fusaoPrimeiro ? primeira : segunda).status, "fundido");
      assert.equal((fusaoPrimeiro ? segunda : primeira).permitido, false);
      assert.equal((await buscar(b.r.id)).id, a.r.id);
      assert.equal((await buscar(b.r.id)).foto_url, url);
      assert.equal((await db.rows(foto(b.r.id, novaUrl(destino))))[0].status, "existente");
      assert.equal((await db.rows(reservar(url)))[0].permitido, false,
        "Compensar por ID antigo não autoriza apagar a foto adotada");
      assert.equal(await estadoMidia(url), undefined);
      assert.deepEqual(await pins(a, b), antes, "Fusão não confirma pins nem reescreve decisão/observação");
      ok(`etapa4 ${destino}: ${fusaoPrimeiro ? "fusão→reserva" : "reserva→fusão"}, foto adotada e pins protegidos pelo ID perdedor`);
    }

    for (const fusaoPrimeiro of [true, false]) {
      const { a, b, i } = await par(); const url = novaUrl(destino);
      await db.rows(foto(b.r.id, url));
      const [[primeira], [segunda]] = fusaoPrimeiro
        ? await disputar(enriquecerSQL(b.e, i), remover(b.r.id))
        : await disputar(remover(b.r.id), enriquecerSQL(b.e, i));
      if (fusaoPrimeiro) {
        assert.equal(primeira.status, "fundido");
        assert.equal(segunda.id, a.r.id);
        assert.equal(await buscar(a.r.id), undefined);
      } else {
        assert.equal(primeira.id, b.r.id);
        assert.equal(segunda.status, "removido");
        assert.equal((await buscar(a.r.id)).foto_url, null);
      }
      assert.equal(await buscar(b.r.id), undefined);
      assert.equal((await db.rows(foto(b.r.id, url)))[0].status, "removida");
      assert.equal((await estadoMidia(url)).estado, "reservada");
      assert.equal((await db.rows(enriquecerSQL(b.e, i)))[0].status, "removido");
      ok(`etapa4 ${destino}: ${fusaoPrimeiro ? "fusão→remoção" : "remoção→fusão"} por ID perdedor, sem ressurreição`);
    }

    const { a, b, i } = await par();
    const mantida = novaUrl(destino);
    const sobra = novaUrl(destino === "local" ? "supabase" : "local");
    await db.rows(foto(a.r.id, mantida)); await db.rows(foto(b.r.id, sobra));
    await db.rows(enriquecerSQL(b.e, i));
    assert.equal((await buscar(b.r.id)).foto_url, mantida);
    assert.equal((await db.rows(reservar(mantida)))[0].permitido, false);
    assert.equal((await estadoMidia(sobra)).estado, "reservada");
    assert.equal(await estadoMidia(mantida), undefined);
    ok(`etapa4: duas fotos de destinos distintos, sobrevivente ${destino} preservado e somente sobra reservada`);
  }

  const raiz = process.env.DEALBOT_TEST_SQL_ARTIFACTS || os.tmpdir();
  assert.ok(path.isAbsolute(raiz), "Diretório de artefatos precisa ser absoluto");
  const diretorio = await fs.mkdtemp(path.join(raiz, "dealbot-sql-etapa4-media-"));
  console.log(`Arquivos sintéticos etapa4 preservados: ${diretorio}`);
  const local = criarMidiaLocalModel(async () => ({ diretorio, limiteBytes: 358400 }));
  const armazenadas = new Set(); const chamadasStorage = [];
  const cliente = {
    async rpc(nome, { p_url }) {
      assert.ok(["midia_reservar_remocao", "midia_confirmar_remocao"].includes(nome));
      return { data: await db.rows(`select * from public.${nome}(${sqlTexto(p_url)})`), error: null };
    },
    storage: { from(bucket) {
      assert.equal(bucket, "produtos");
      return { async remove(chaves) {
        chamadasStorage.push(chaves);
        for (const chave of chaves) armazenadas.delete(chave);
        return { error: null };
      } };
    } },
  };
  const model = criarLimpezaModel(async () => cliente, async () => ORIGEM, local);
  const publicar = async () => {
    const url = novaUrl();
    await fs.writeFile(path.join(diretorio, url.slice(7)), WEBP, { flag: "wx" });
    return url;
  };
  const ler = (url) => fs.readFile(path.join(diretorio, url.slice(7)));
  const ausente = (url) => assert.rejects(ler(url), { code: "ENOENT" });
  const limpar = (url, alteracoes = {}) => criarExecutarLimpeza({
    ...model,
    // Isola a candidata conhecida: descoberta/limites da RPC oferta_limpar são
    // exercitados pelos 47 grupos históricos; reserva/delete/ack aqui são reais.
    async prepararLote() { return { urls: [url], processadas: 0, continuar: false }; },
    ...alteracoes,
  }, async () => ({ retencaoHoras: 48, retencaoDias: 7, limpezaLote: 100, limpezaMaxLotes: 1 }),
  { log() {}, warn() {}, error() {} })();

  const { a, b, i } = await par(); const adotada = await publicar();
  await db.rows(foto(b.r.id, adotada)); await db.rows(enriquecerSQL(b.e, i));
  assert.deepEqual(await local.ler(adotada.slice(7)), { dados: WEBP, tamanho: WEBP.length });
  assert.equal((await limpar(adotada)).fotos, 0);
  assert.deepEqual(await ler(adotada), WEBP);
  assert.equal((await buscar(b.r.id)).foto_url, adotada);
  assert.equal(await estadoMidia(adotada), undefined);
  ok("etapa4 físico: model/service reais + reserva SQL negada conservam bytes da foto adotada");

  const falha = await publicar(); const intocada = await publicar();
  const primeira = await limpar(falha, { async apagarFoto() {
    throw Object.assign(new Error("I/O sintético antes de unlink"), { code: "EIO" });
  } });
  assert.equal(primeira.falhas, 1); assert.equal(primeira.fotos, 0);
  assert.deepEqual(await ler(falha), WEBP);
  assert.equal((await estadoMidia(falha)).estado, "reservada");
  const segunda = await limpar(falha, { async confirmarRemocao() { throw new Error("Confirmação não enviada"); } });
  assert.equal(segunda.falhas, 1); await ausente(falha);
  assert.equal((await estadoMidia(falha)).estado, "reservada");
  const terceira = await limpar(falha);
  assert.equal(terceira.falhas, 0); assert.equal(terceira.fotos, 1);
  assert.equal((await estadoMidia(falha)).estado, "removida");
  assert.deepEqual(await ler(intocada), WEBP, "Final desconhecido não é varrido");
  ok("etapa4 físico: EIO injetado e falha antes do ack preservam pendência; retry comprova ausência antes de confirmar");

  const respostaPerdida = await publicar();
  const perdida = await limpar(respostaPerdida, { async confirmarRemocao(url) {
    await model.confirmarRemocao(url);
    throw new Error("Resposta perdida após commit real");
  } });
  assert.equal(perdida.falhas, 1); await ausente(respostaPerdida);
  assert.equal((await estadoMidia(respostaPerdida)).estado, "removida");
  const retomada = await limpar(respostaPerdida);
  assert.equal(retomada.fotos, 1); assert.equal(retomada.falhas, 0);
  assert.equal((await estadoMidia(respostaPerdida)).estado, "removida");
  assert.equal((await db.rows(foto(a.r.id, respostaPerdida)))[0].status, "existente");
  const semFoto = await novoCard();
  assert.equal((await db.rows(foto(semFoto.r.id, respostaPerdida)))[0].status, "remocao_reservada");
  ok("etapa4 físico: ack com commit/resposta perdida é retomável sem apagar tombstone nem permitir novo vínculo");

  const invalida = await publicar(); const chave = invalida.slice(7);
  for (const url of [
    `${ORIGEM}${invalida}`, `/media/%${chave.charCodeAt(0).toString(16)}${chave.slice(1)}`,
    `${invalida}?x=1`, `${invalida}#x`, `//projeto.invalid${invalida}`,
    `https://outro.invalid/storage/v1/object/public/produtos/${chave}`,
    `${ORIGEM}/storage/v1/object/public/outro/${chave}`,
    `${ORIGEM}/storage/v1/object/public/produtos/%${chave.charCodeAt(0).toString(16)}${chave.slice(1)}`,
  ]) {
    const resultado = await limpar(url);
    assert.equal(resultado.falhas, 1); assert.equal(resultado.fotos, 0);
    assert.equal((await estadoMidia(url)).estado, "reservada", "Não confirmar URL que não autorizou remoção física");
    assert.deepEqual(await ler(invalida), WEBP);
  }
  assert.deepEqual(chamadasStorage, []);
  ok("etapa4: host/bucket/encoding/query/fragmento/protocolo relativo inválidos não apagam por basename nem recebem ack falso");

  // A API não consulta o modo de escrita do bot. Ambos destinos continuam
  // removíveis usando exclusivamente a URL congelada, sem copiar/varrer mídia.
  const modoAnterior = process.env.BOT_MIDIA_MODO;
  try {
    process.env.BOT_MIDIA_MODO = "supabase";
    const urlLocal = await publicar(); const urlLegada = novaUrl("supabase");
    const chaveLegada = urlLegada.split("/").at(-1);
    armazenadas.add(chaveLegada);
    assert.equal((await limpar(urlLocal)).fotos, 1); await ausente(urlLocal);
    assert.deepEqual(chamadasStorage, [], "Foto local nunca chama Storage");
    assert.equal((await limpar(urlLegada)).fotos, 1);
    assert.equal(armazenadas.has(chaveLegada), false);
    assert.deepEqual(chamadasStorage, [[chaveLegada]]);
    assert.deepEqual(await ler(adotada), WEBP);
    assert.deepEqual(await ler(intocada), WEBP);
  } finally {
    if (modoAnterior === undefined) delete process.env.BOT_MIDIA_MODO;
    else process.env.BOT_MIDIA_MODO = modoAnterior;
  }
  ok("etapa4: modo de escrita Supabase conserva limpeza dual; arquivo local real/Storage falso são despachados pela URL exata");

  // Sem fabricar ack para liberar retenção: somente a RPC pública o confirma.
  await db.rows(remover(b.r.id));
  await db.exec(`update public.produtos set terminal_em=now()-interval '8 days'
    where id in (${a.r.id},${b.r.id});`);
  await db.rows("select * from public.oferta_limpar()");
  assert.equal(await contar("produtos", `id in (${a.r.id},${b.r.id})`), 2);
  for (const card of [a, b]) {
    assert.equal((await db.rows(`select pin from public.oferta_eventos where canal_id=${card.e.canal_id} and msg_id=1`))[0].pin, true);
    await db.rows(`select * from public.oferta_confirmar(${card.e.canal_id},1)`);
  }
  await db.rows("select * from public.oferta_limpar()");
  assert.equal(await contar("produtos", `id in (${a.r.id},${b.r.id})`), 2, "Ack recente ainda protege retenção");
  ok("etapa4: mídia local/alias removidos conservam pins até RPC de ack e retenção após confirmação");
}
