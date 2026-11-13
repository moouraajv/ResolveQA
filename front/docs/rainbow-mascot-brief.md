# Mola arco-íris: desenho e movimento

Pedido: aplicar no frontend o desenho da prancha 01, a interação de pegar/transportar/entregar da prancha 02 e cores arco-íris; estudar o repertório do pinguim da Keytotwo para obter movimento fluido.

Base preservada: commit `1eaa6a1`, incluindo as alterações já feitas pelo Cursor. Não desfazer tarefas, snapshots, filtros ou os limites de persistência existentes.

## Escopo de implementação — Cursor

Escrever somente `components/mola/`, `app/page.tsx` e `app/globals.css`. Codex prepara arte, atlas, documentação, revisão, build, Git e publicação. Não redesenhar o mascote em SVG ou canvas: a arte final será um atlas de sprites gerados por Imagegen, com identidade baseada na prancha 01. O desenho procedural atual será substituído.

Atlas previsto: `/mascot/mola-rainbow/atlas.png`, 1536x1872 px, 8 colunas, células 192x208 px, nove linhas. Linhas: idle(6), running-right(8), running-left(8), waving(4), jumping(5), failed(8), waiting(6), running/work(6), review(6). São os estados intermediários de animação da metodologia Create Pet, adaptados ao frontend, sem criar um Pet do ChatGPT. Codex confirmará este contrato após a composição. Durante implementação os assets podem ainda não existir: não criar outro mascote como fallback.

## Comportamento

Estudar como referência os estados públicos em `https://keytotwo.com.br/assets/kito-sprites-uv_CWNcn.js` e o comportamento de `https://keytotwo.com.br/assets/kito-playground-D6LdSuaS.js`. Arquivos de referência local: `/tmp/keytotwo-kito-sprites.js` e `/tmp/keytotwo-playground.js`. Escrever lógica própria; não incorporar o código nem os sprites do pinguim ao projeto.

- Hero: mascote com locomoção direcional, respiração/piscar de idle, saudação, salto e espera. Pode seguir o ponteiro dentro do palco com aceleração/frenagem gradual; arrastar e soltar no palco produz retorno elástico e reação de surpresa. Interação não deve bloquear rolagem mobile fora do hitbox. Adicionar controle acessível para saltar/saudar e pausar movimento se necessário, sem poluir a interface.
- Repertório inspirado na referência: andar/correr com cadência dependente da velocidade, mudar direção sem teleportar, antecipar salto, aterrissar, saudar, carregar e reagir a soltar. Não apresentar como cópia exata de todos os 17 clipes do pinguim.
- Transporte do card no Kanban: antecipação/comprimir → alcançar/pegar → deslocamento fluido carregando o card → entregar → comemorar. Um card só muda de coluna depois da entrega. O card precisa manter uma âncora coerente em relação ao sprite, sem duplicação de prop desenhada e DOM.
- Preferir trajetória controlada por requestAnimationFrame com delta de tempo limitado e easing/mola amortecida; não usar vários setTimeout independentes para controlar a mesma sequência. Movimento espacial suave a 60 fps e frames da arte em cadence discreta. Não recalcular React em cada pixel se refs/estilo direto resolverem com segurança.
- Uma única fila/lock de transporte. Cancelar raf/listeners corretamente. Pausar loops ocultos/fora de viewport. Redução de movimento respeitada; tarefas continuam funcionais.
- Paleta padrão multicolorida arco-íris. Conservar seletores se funcionarem como rotações de matiz do mesmo personagem, com rótulos claros; não recolorir de forma que destrua outlines/pixels. Não deixar o usuário achar que a cor padrão continua monocromática.
- Preservar mobile, teclado, diálogos, importação/exportação e modo demonstração explícito. Corrigir eventual origem/destino offscreen durante scroll; nada de card saltando ao terminar.

## Aceite

Desenho do arquivo gerado aparece no hero e no card transportado. Estados sprite efetivamente distintos e movimento físico contínuo. Sem laços de animação concorrentes, sem avanço duplicado, sem esconder controles. `npx tsc --noEmit` passa. Não rodar build/commit/publicação; relatar arquivos, verificações, exit codes e limitações com `maestri ask "Codex" "<resultado>"` ao concluir.
