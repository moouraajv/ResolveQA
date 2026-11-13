# Mola arco-íris — arte e runtime

O desenho mantém as espiras abertas, olhos e pés da prancha **Playful Paper**. A cor padrão é arco-íris, com traseira violeta e frente vermelha. As outras opções giram a matiz da mesma arte. O transporte segue a ideia da prancha **After Hours**: comprimir, pegar, carregar, entregar e comemorar.

A metodologia de identidade, geração por estado e inspeção da skill Create Pet foi adaptada para esta aplicação web. Não foi criado um Pet do ChatGPT, nem há registro no serviço Pets/Library. O atlas usa somente os nove estados de animação do layout intermediário de 1536×1872; não é uma entrega Work v2 de onze linhas com dezesseis direções de olhar.

## Arte reproduzível e evidência

- Referência: [prancha 01](../public/moodboards/mola-paper.png).
- Base aceita: [canonical-base.png](../artwork/mola-rainbow-v2/references/canonical-base.png).
- Fontes e prompts: [run completo](../artwork/mola-rainbow-v2/), incluindo fontes rejeitadas e relatórios reais.
- [Atlas distribuído](../public/mascot/mola-rainbow/atlas.png): PNG RGBA, 1536×1872, oito colunas, células 192×208, 57 frames e quinze células transparentes.
- SHA256: `68d32b5e21a4c5c6ffffa556b3ed17f82b1b89e9529246736014e1f81b0b9bc7`.
- [Validação do arquivo codificado](../artwork/mola-rainbow-v2/final/validation.json), [inspeção de frames](../artwork/mola-rainbow-v2/qa/review.json) e [despill](../artwork/mola-rainbow-v2/qa/chroma-despill.json).
- [Contato de todas as poses](../artwork/mola-rainbow-v2/qa/contact-sheet.png), [GIF](../public/mascot/mola-rainbow/motion.gif), [MP4](../public/mascot/mola-rainbow/motion.mp4) e [idle → salto → idle](../public/mascot/mola-rainbow/idle-jump-idle.gif).

As fontes foram geradas por Imagegen por estado, ancoradas na mesma base. Os scripts bundled de `create-pet/scripts` extraíram os grupos conectados com escala compartilhada por linha; nenhuma pose foi redesenhada ou redimensionada individualmente. A corrida para a esquerda foi derivada pelo script de espelhamento pose a pose, preservando a ordem temporal, após aprovação da simetria e ausência de acessórios com lateralidade.

| Linha | Estado | Frames | Threshold de extração escolhido |
| --- | --- | ---: | ---: |
| 0 | idle | 6 | 120 |
| 1 | running-right | 8 | 130 |
| 2 | running-left | 8 | 130 |
| 3 | waving | 4 | 96 |
| 4 | jumping | 5 | 120 |
| 5 | failed | 8 | 128 |
| 6 | waiting | 6 | 96 |
| 7 | running / work | 6 | 128 |
| 8 | review | 6 | 120 |

A limpeza de borda foi aplicada uma vez ao atlas composto, preservando alfa. A validação final passou sem erros e sem avisos. Os pequenos highlights claros junto às espiras violetas foram examinados; não interrompem a identidade nem eliminam essa cor. Os frames de salto têm apoio y201 no início/fim e y143 no ápice. O runtime ancora a célula no apoio de descanso, preservando a altura desenhada.

## Movimento

Referência comportamental: [Keytotwo](https://keytotwo.com.br/), especialmente os módulos públicos [kito-sprites](https://keytotwo.com.br/assets/kito-sprites-uv_CWNcn.js) e [kito-playground](https://keytotwo.com.br/assets/kito-playground-D6LdSuaS.js), estudados em 2026-11-07. Inspiram aceleração, frenagem, cadência, arrastar, reação e pontos de pega. O código e os sprites do pinguim não são distribuídos neste projeto; o repertório adaptado não pretende reproduzir todos os clipes da referência.

O hero atualiza posições e frames por refs com um RAF. O transporte tem um RAF próprio e um lock de tarefa; o card DOM apoia na espira usando pontos medidos por frame. O quadro muda após a fase de entrega. Scroll remede o destino e resize encerra com atualização segura. Pausa, visibilidade e preferência de movimento reduzido preservam o uso do quadro.

A interface permanece demonstrativa e local, sem conexão em tempo real ao backend, GitHub ou Maestri.
