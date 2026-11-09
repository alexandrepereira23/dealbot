// Contratos SQL da revisão: fixtures explícitas de cópia, SEM afirmar
// equivalência comercial ausente. Adaptador/pipeline reais são cobertos no bot.
// Executado pelo runner sql-etapa3.local.mjs, inclusive sua barreira pg_locks.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";

const destino = "https://www.amazon.com.br/dp/B012345678?smid=SELLER1";
const conteudo = "Notebook 16 GB\nPor R$ 2.499,90 no Pix\n<COMPRA>";
const comparacao = (campos = {}) => ({ destino, conteudo, preco_centavos: 249990,
  condicoes: { pagamento: "pix" }, ...campos });
const assinatura = (valor) => createHash("sha256").update(JSON.stringify(valor)).digest("hex");
function copia(identidade, campos = {}, forte = null) {
  const cmp = comparacao(campos);
  const comercial = forte === null ? identidade(null)
    : identidade(forte, { loja: "sintetica", revisao: "copias_post", variante: forte });
  return { ...comercial, copia: { versao: 1, chave: assinatura(cmp), comparacao: cmp } };
}
const post = (produto, link = destino, campos = {}) => ({ ...produto(2499.90),
  titulo: "Notebook 16 GB", preco_original: null, cupom: null,
  link, raw_text: `Notebook 16 GB\nPor R$ 2.499,90 no Pix\n${link}`, ...campos });
const mapa = (db, e) => db.rows(`select * from public.oferta_eventos
  where canal_id=${e.canal_id} and msg_id=${e.msg_id}`);
const observacoes = (db, canais) => db.rows(`select canal_id,observacao->>'link' as link,
  observacao->>'preco' as preco,pin,identidade_inicial from public.oferta_eventos
  where canal_id in (${canais.join(",")}) order by canal_id desc`);

export async function validarRevisao3(h) {
  const { db, evento, produto, identidade, literal, registrar, enriquecerSQL,
    buscar, contar, dadosOfertas, ok } = h;

  await db.exec("begin;");
  const fraca = copia(identidade);
  const forteA = copia(identidade, {}, "a");
  const forteB = copia(identidade, {}, "b");
  const mesmoHashOutroTexto = structuredClone(fraca);
  mesmoHashOutroTexto.copia.comparacao.conteudo += "\nExclusivo para assinantes";
  for (const [a, b, esperado] of [
    [fraca, structuredClone(fraca), true], [fraca, identidade(null), false],
    [fraca, mesmoHashOutroTexto, false], [forteA, forteB, false],
    [forteA, fraca, false], [fraca, forteA, false],
    [identidade("a"), identidade("a"), true],
    [identidade("a"), identidade("a", { variante: "outra" }), false],
  ]) {
    const [r] = await db.rows(`select public._oferta_equivalentes(${literal(a)},${literal(b)}) as igual`);
    assert.equal(r.igual, esperado, "Comparador não usa cópia como ponte comercial nem hash isolado");
  }
  await db.exec("rollback;");
  ok("revisão: comparador aditivo mantém v2 congelada e separa cópia de equivalência comercial");

  for (const [n, url, links] of [
    [0, "https://produto.mercadolivre.com.br/MLB-1234567890", [
      "https://produto.mercadolivre.com.br/MLB-1234567890",
      "https://produto.mercadolivre.com.br/MLB-1234567890"]],
    [1, destino, [`${destino}&tag=canal-a-20`, `${destino}&tag=canal-b-20`]],
  ]) {
    await db.exec("begin;");
    const i = copia(identidade, { destino: url });
    const ea = evento(-103001 - n * 10, 1);
    const eb = evento(-103002 - n * 10, 1, 1);
    const pa = post(produto, links[0]); const pb = post(produto, links[1]);
    const a = await registrar(ea, pa, i); const b = await registrar(eb, pb, i);
    assert.equal(i.chave, null, "Fixture de cópia não inventa identidade forte");
    assert.equal(a.id, b.id);
    assert.equal(await contar("produto_aparicoes", `produto_id=${a.id}`), 2);
    assert.equal(await contar("oferta_eventos", `produto_id=${a.id}`), 2);
    assert.deepEqual((await observacoes(db, [ea.canal_id, eb.canal_id])).map((r) => r.link), links);
    assert.equal((await buscar(a.id)).preco, 2499.90);
    const antes = await dadosOfertas();
    for (const [e, p] of [[ea, pa], [eb, pb]]) assert.equal((await registrar(e, p, i)).id, a.id);
    assert.deepEqual(await dadosOfertas(), antes, "Retry de cópia preserva snapshot completo");
    await db.exec("rollback;");
  }
  ok("revisão: cópias diretas em dois canais, Mercado Livre/Amazon sem tag, links originais e retry exato");

  await db.exec("begin;");
  const base = copia(identidade);
  const principal = await registrar(evento(-103101, 1), post(produto), base);
  const estadoAntesInvalidos = await dadosOfertas();
  await db.exec(`do $prova$ declare recusada boolean := false; begin
    begin
      perform public.oferta_registrar(${literal(evento(-103199,1))},
        ${literal(post(produto, destino, { preco: 2500 }))},${literal(base)},48);
    exception when invalid_parameter_value then recusada := true; end;
    if not recusada then raise exception 'Cópia não pode esconder preço diferente na observação'; end if;
  end $prova$;`);
  const [precoInvalido] = await db.rows(enriquecerSQL(evento(-103101,1),
    copia(identidade, { preco_centavos: 250000 })));
  assert.equal(precoInvalido.status, "conflito");
  assert.deepEqual(await dadosOfertas(), estadoAntesInvalidos);
  let canal = -103102;
  for (const alteracao of [
    { preco_centavos: 249991 }, { destino: `${destino}&variant=Outra` },
    { destino: destino.replace("SELLER1", "SELLER2") },
    { conteudo: `${conteudo}\nKit com 2 unidades` },
    { condicoes: { pagamento: "pix", cupom: "EXCLUSIVO" } },
    { condicoes: { pagamento: "pix", elegibilidade: "assinantes" } },
    { condicoes: { pagamento: "cartao" } },
  ]) {
    const i = copia(identidade, alteracao);
    // Colisão deliberada: a comparação completa deve vetar mesmo com hash igual.
    i.copia.chave = base.copia.chave;
    const p = post(produto, i.copia.comparacao.destino,
      { preco: i.copia.comparacao.preco_centavos / 100 });
    assert.notEqual((await registrar(evento(canal--, 1), p, i)).id, principal.id);
  }
  const chaveDiferente = structuredClone(base);
  chaveDiferente.copia.chave = "f".repeat(64);
  assert.notEqual((await registrar(evento(canal--, 1), post(produto), chaveDiferente)).id, principal.id);
  assert.notEqual((await registrar(evento(canal--, 1), post(produto), identidade(null))).id, principal.id);
  await db.exec("rollback;");
  ok("revisão: preço/destino/seller/texto/kit/cupom/elegibilidade diferentes não unem cópias, inclusive colisão de hash");

  for (const ordem of [["a", "b", null], [null, "b", "a"]]) {
    await db.exec("begin;");
    const cards = new Map(); let canal = -103201;
    for (const forte of ordem) {
      const e = evento(canal--, 1);
      const i = copia(identidade, {}, forte);
      cards.set(forte, { e, i, r: await registrar(e, post(produto), i) });
    }
    assert.equal(new Set([...cards.values()].map(({ r }) => r.id)).size, 3,
      "Cópia fraca não une fortes incompatíveis, em nenhuma ordem");
    for (const forte of ["a", "b"]) {
      const { e, i, r } = cards.get(forte);
      const [antes] = await db.rows(`select identidade_chave,identidade_dados from public.produtos where id=${r.id}`);
      const [enriquecida] = await db.rows(enriquecerSQL(e, copia(identidade)));
      assert.equal(enriquecida.id, r.id);
      assert.deepEqual((await db.rows(`select identidade_chave,identidade_dados from public.produtos where id=${r.id}`))[0], antes,
        "Enriquecimento copy-only nunca apaga uma identidade comercial forte");
      assert.equal((await registrar(evento(canal--, 1), post(produto), i)).id, r.id);
    }
    const canonicos = [];
    for (const { r } of cards.values()) canonicos.push((await buscar(r.id)).id);
    assert.equal(new Set(canonicos).size, 3);
    // Resolver a fraca para A permite somente a equivalência comercial A;
    // a cópia comum jamais pode arrastar B para essa fusão.
    const fraca = cards.get(null); const a = cards.get("a"); const b = cards.get("b");
    const [resolvida] = await db.rows(enriquecerSQL(fraca.e, a.i));
    assert.equal(resolvida.id, Math.min(fraca.r.id, a.r.id));
    assert.equal((await buscar(fraca.r.id)).id, resolvida.id);
    assert.equal((await buscar(a.r.id)).id, resolvida.id);
    assert.equal((await buscar(b.r.id)).id, b.r.id);
    assert.notEqual(b.r.id, resolvida.id);
    assert.equal(await contar("oferta_eventos", `produto_id=${b.r.id}`), 2);
    await db.exec("rollback;");
  }
  ok("revisão: fortes A/B e cópia fraca não fazem ponte nas duas ordens; enriquecimento fraco não apaga forte");

  await db.exec("begin;");
  const ea = { ...evento(-103301, 1), enriquecer: true };
  const eb = { ...evento(-103302, 1, 1), enriquecer: true };
  const pa = post(produto, "https://amzn.to/DealA");
  const pb = post(produto, "https://amzn.to/DealB");
  const a = await registrar(ea, pa, identidade(null)); const b = await registrar(eb, pb, identidade(null));
  assert.notEqual(a.id, b.id);
  assert.ok(await buscar(a.id)); assert.ok(await buscar(b.id));
  await db.rows(`select * from public.oferta_foto(${b.id},'https://midia.invalid/revisao-copia.jpg')`);
  const originais = await observacoes(db, [ea.canal_id, eb.canal_id]);
  assert.ok(originais.every((r) => r.pin), "Referências de resolução pendente permanecem recuperáveis");
  const resolvida = copia(identidade);
  await db.rows(enriquecerSQL(ea, resolvida));
  const [fusao] = await db.rows(enriquecerSQL(eb, resolvida));
  assert.equal(fusao.id, Math.min(a.id, b.id));
  for (const r of [a, b]) {
    const card = await buscar(r.id);
    assert.equal(card.id, fusao.id); assert.equal(card.preco, 2499.90);
    assert.equal(card.foto_url, "https://midia.invalid/revisao-copia.jpg");
  }
  assert.equal(await contar("produto_aparicoes", `produto_id=${fusao.id}`), 2);
  assert.equal(await contar("oferta_eventos", `produto_id=${fusao.id}`), 2);
  assert.deepEqual(await observacoes(db, [ea.canal_id, eb.canal_id]), originais,
    "Fusão preserva observações, links, preços, pins e decisões iniciais");
  const fundidas = await dadosOfertas();
  assert.equal((await registrar(ea, pa, identidade(null))).id, fusao.id);
  assert.equal((await registrar(eb, pb, identidade(null))).id, fusao.id);
  assert.deepEqual(await dadosOfertas(), fundidas);
  await db.exec("rollback;");
  ok("revisão: resolução funde provisórios copy-only, mantém aliases/foto/pins/preços/links e decisões congeladas");

  const agora = Date.now();
  const historico = (canal, horas) => ({ ...evento(canal, 1), data_origem: new Date(agora - horas * 3600000).toISOString() });
  for (const inversa of [false, true]) for (const limpar of [false, true]) {
    await db.exec("begin;");
    const i = identidade("c", { revisao: "49h_2h", inversa, limpar });
    const antigo = historico(-103401, 49); const recente = historico(-103402, 2);
    let velha; let nova; let vinculoAntigo;
    if (inversa) {
      nova = await registrar(recente, produto(250), i);
      if (limpar) await db.rows("select * from public.oferta_limpar()");
      velha = await registrar(antigo, produto(300), i);
      vinculoAntigo = (await mapa(db, antigo))[0].produto_id;
    } else {
      velha = await registrar(antigo, produto(300), i);
      vinculoAntigo = (await mapa(db, antigo))[0].produto_id;
      assert.equal(await buscar(velha.id), undefined, "Histórico expirado sozinho nunca aparece");
      if (limpar) await db.rows("select * from public.oferta_limpar()");
      nova = await registrar(recente, produto(250), i);
    }
    assert.equal((await mapa(db, antigo))[0].produto_id, vinculoAntigo,
      "Escolher instância nova ou reabrir a elegível não transfere silenciosamente evento antigo");
    const candidatas = await db.rows(`select id from public.produtos where identidade_dados=${literal(i)}`);
    const visiveis = [];
    for (const { id } of candidatas) {
      const visivel = await buscar(id);
      if (visivel) visiveis.push(visivel);
    }
    assert.equal(new Set(visiveis.map((p) => p.id)).size, 1, `Uma visível: inversa=${inversa}, limpeza=${limpar}`);
    const card = await buscar(nova.id);
    assert.ok(card, "Evento válido não pode receber sucesso numa instância invisível");
    assert.equal(card.preco, 250);
    assert.equal(Date.parse(card.expira_em), Date.parse(recente.data_origem) + 48 * 3600000);
    assert.equal(Date.parse(card.ultima_aparicao_em), Date.parse(recente.data_origem));
    const antes = await dadosOfertas();
    const retry = await registrar({ ...antigo, recebido_em: new Date().toISOString() }, produto(300), i);
    assert.equal(retry.id, velha.id);
    assert.deepEqual(await dadosOfertas(), antes, "Replay antigo não renova nem duplica aparição");
    await db.exec("rollback;");
  }
  ok("revisão: 49h/300 e 2h/250 nas duas ordens, com/sem limpeza, uma visível até data recente+48h e replay exato");

  await db.exec("begin;");
  const iExpirada = identidade("d", { revisao: "historico_invalido" });
  const expirada = await registrar(historico(-103501, 49), produto(300), iExpirada);
  await db.rows("select * from public.oferta_limpar()");
  const [antesExpirada] = await db.rows(`select * from public.produtos where id=${expirada.id}`);
  for (const [canal, data_origem] of [[-103502, "inválida"], [-103503, new Date(agora + 86400000).toISOString()]]) {
    const r = await registrar({ ...evento(canal, 1), data_origem }, produto(250), iExpirada);
    assert.equal(await buscar(r.id), undefined);
  }
  await registrar(historico(-103504, 50), produto(200), iExpirada);
  assert.equal(await buscar(expirada.id), undefined);
  assert.deepEqual((await db.rows(`select * from public.produtos where id=${expirada.id}`))[0], antesExpirada,
    "Histórico anterior/data inválida/futura não reabre nem reescreve card expirado");
  await db.exec("rollback;");
  ok("revisão: data inválida/futura e histórico antigo sozinho nunca reativam oferta expirada");

  await db.exec("begin;");
  const iGap = identidade("e", { revisao: "lacuna_maior_48h" });
  const old = await registrar(historico(-103601, 51), produto(300), iGap);
  const recente = historico(-103602, 2);
  const atual = await registrar(recente, produto(250), iGap);
  assert.notEqual(old.id, atual.id);
  assert.equal(await buscar(old.id), undefined);
  assert.equal((await buscar(atual.id)).preco, 250);
  const iRemovida = identidade("f", { revisao: "remocao_terminal" });
  const removida = await registrar(historico(-103611, 49), produto(300), iRemovida);
  await db.rows(`select * from public.oferta_remover(${removida.id})`);
  await db.rows("select * from public.oferta_limpar()");
  const tentativa = await registrar(historico(-103612, 2), produto(250), iRemovida);
  assert.equal(tentativa.id, removida.id); assert.equal(tentativa.status, "removido");
  assert.equal(await buscar(removida.id), undefined);
  await db.exec("rollback;");
  ok("revisão: lacuna >48h separa instâncias; promoção recente não ressuscita exclusão manual");
}

export async function validarRevisao3Concorrente(h) {
  const { db, evento, produto, identidade, registrar, registrarSQL, enriquecerSQL,
    buscar, contar, dadosOfertas, disputar, ok } = h;
  const i = copia(identidade, { conteudo: `${conteudo}\nFixture concorrente direta` });
  const ea = evento(-103701, 1); const eb = evento(-103702, 1, 1);
  const pa = post(produto, `${destino}&tag=canal-a-20`);
  const pb = post(produto, `${destino}&tag=canal-b-20`);
  const [[a], [b]] = await disputar(registrarSQL(ea, pa, i), registrarSQL(eb, pb, i));
  assert.equal(a.id, b.id);
  assert.equal(await contar("produto_aparicoes", `produto_id=${a.id}`), 2);
  assert.equal(await contar("oferta_eventos", `produto_id=${a.id}`), 2);
  const antes = await dadosOfertas();
  await disputar(registrarSQL(ea, pa, i), registrarSQL(eb, pb, i));
  assert.deepEqual(await dadosOfertas(), antes);
  ok("revisão concorrente: primeira criação copy-only em duas sessões/barreira pg_locks converge e retries não escrevem");

  const ec = { ...evento(-103711, 1), enriquecer: true };
  const ed = { ...evento(-103712, 1, 1), enriquecer: true };
  const pc = post(produto, "https://amzn.to/ConcorrenteA");
  const pd = post(produto, "https://amzn.to/ConcorrenteB");
  const c = await registrar(ec, pc, identidade(null)); const d = await registrar(ed, pd, identidade(null));
  assert.notEqual(c.id, d.id); assert.ok(await buscar(c.id)); assert.ok(await buscar(d.id));
  const originais = await observacoes(db, [ec.canal_id, ed.canal_id]);
  const resolvida = copia(identidade, { conteudo: `${conteudo}\nFixture concorrente resolvida` });
  const [[rc], [rd]] = await disputar(enriquecerSQL(ec, resolvida), enriquecerSQL(ed, resolvida));
  const canonico = Math.min(c.id, d.id);
  assert.equal(rc.id, canonico); assert.equal(rd.id, canonico);
  assert.equal((await buscar(c.id)).id, canonico); assert.equal((await buscar(d.id)).id, canonico);
  assert.equal(await contar("produto_aparicoes", `produto_id=${canonico}`), 2);
  assert.equal(await contar("oferta_eventos", `produto_id=${canonico}`), 2);
  assert.deepEqual(await observacoes(db, [ec.canal_id, ed.canal_id]), originais);
  const fundidas = await dadosOfertas();
  assert.equal((await registrar(ec, pc, identidade(null))).id, canonico);
  assert.equal((await registrar(ed, pd, identidade(null))).id, canonico);
  assert.deepEqual(await dadosOfertas(), fundidas);
  ok("revisão concorrente: enriquecimentos copy-only convergem com aliases e duas observações/pins originais");
}
