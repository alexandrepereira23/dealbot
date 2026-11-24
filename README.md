# Dealbot

O Dealbot monitora canais do Telegram e reúne as ofertas em um painel web.
Em vez de acompanhar cada canal separadamente, é possível consultar promoções
por categoria, acessar o link de compra e copiar cupons em um só lugar.

[Início rápido](#início-rápido) · [Arquitetura](#arquitetura) · [Documentação](#documentação) · [Contribuição](#contribuição)

## Funcionalidades

- **Coleta configurável:** monitora os canais cadastrados e aplica regras de
  interesse e bloqueio por palavras-chave, categoria e limite de preço.
- **Extração e deduplicação:** extrai preço, link e cupom das mensagens e evita
  republicar a mesma oferta quando há evidência suficiente de equivalência.
- **Painel autenticado:** lista ofertas e métricas por categoria e permite
  gerenciar as regras de captura.
- **Processamento em segundo plano:** a fila persistente permite retomar o
  trabalho após interrupções. As fotos são vinculadas ao card sem impedir que a
  oferta apareça antes.

## Início rápido

A demonstração executa o painel com dados e login sintéticos, sem conectar a um
projeto Supabase nem ao Telegram. Requer Docker com containers Linux e Docker
Compose v2.30 ou superior. Não é necessário instalar Node.js ou Python no host.

Na raiz do repositório:

```sh
docker compose -p dealbot-etapa5-lab -f deploy/lab/compose.yaml up -d --build
```

Configure o [certificado HTTPS do laboratório](docs/uso-local.md#certificado-https-local)
e abra **<https://localhost:18443>**. O [roteiro da demonstração](docs/uso-local.md#modo-a--demonstração-sem-credenciais)
contém o login de teste e os comandos para gerar uma oferta, liberar sua foto e
parar o ambiente.

Para conectar dados reais, siga o [guia de execução local](docs/uso-local.md#modo-b--uso-real-no-computador).
Esse ambiente usa projeto e volumes separados e não inicia a coleta Telegram
por padrão.

## Arquitetura

```text
Telegram ──► Coletor ──► Supabase (PostgreSQL)
                ├──────► Fila SQLite
                └──────► Volume WebP ◄────┐
                                          │
Navegador ──► Caddy ──┬──► Painel         │
                      └──► API ───────────┘
                            └──► Supabase (Auth e PostgreSQL)
```

O coletor usa SQLite para a fila e os checkpoints. A API consulta os dados no
Supabase após validar a sessão do painel. O Caddy serve o painel, `/api` e
`/media` na mesma origem. No Compose, o bot e a API compartilham o volume de
fotos WebP, não o banco SQLite.

| Diretório | Responsabilidade |
| --- | --- |
| [`bot/`](bot/) | Coleta, extração, filtros e mídia — Python 3.12, Telethon e SQLite. |
| [`backend/`](backend/) | API REST, autenticação e serviço de mídia — Node.js 24 e Express. |
| [`frontend/`](frontend/) | Painel, login e gerenciamento de filtros — Next.js 16, React e TypeScript. |
| [`supabase/`](supabase/) | Schema PostgreSQL, políticas de acesso e funções do banco. |
| [`deploy/`](deploy/) | Docker Compose, Caddy, laboratório e scripts operacionais. |

## Documentação

| Guia | Conteúdo |
| --- | --- |
| [Execução local](docs/uso-local.md) | Demonstração, configuração, coleta Telegram, HTTPS e backup. |
| [Testes](docs/testes.md) | Suítes por componente, ensaio integrado e critérios de validação. |
| [Implantação em VPS](docs/deploy-vps.md) | Topologia, migração, verificação e rollback. |

## Contribuição

Use o laboratório ou um ambiente de testes separado para reproduzir alterações.
Antes de abrir um PR, execute as [suítes dos componentes afetados](docs/testes.md#suítes-por-componente)
e descreva como a mudança foi validada. Se alterar configuração ou operação,
atualize o exemplo de configuração e o guia correspondente. Não inclua arquivos
`.env`, tokens, sessões do Telegram nem dados privados nos commits ou exemplos.
