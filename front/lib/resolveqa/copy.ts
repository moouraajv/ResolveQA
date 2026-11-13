const agents: Record<string, string> = {
  Triage: "Triagem",
  Reproducer: "Reprodução",
  Fixer: "Correção",
  Verifier: "Verificação",
};
export const agentLabel = (value: string) => agents[value] || value;
const sources: Record<string, string> = {
  intake: "Recebimento",
  orchestrator: "Coordenação",
  triage: "Triagem",
  reproduction: "Reprodução",
  fix: "Correção",
  verification: "Verificação",
  delivery: "Entrega",
  reply: "Resposta",
};
export const sourceLabel = (value: string) => sources[value] || value;
const activities: Record<string, string> = {
  CaseCreated: "Relato recebido",
  StateChanged: "Etapa atualizada",
  EvidenceAdded: "Comprovante adicionado",
  LimitReached: "Limite de tentativas atingido",
  MessageSent: "Mensagem enviada",
  ReplayStarted: "Histórico revisitado",
};
export const activityLabel = (value: string) => activities[value] || value;
export const resultLabel = (value: string) =>
  ({ ok: "Concluída", error: "Precisa de atenção", running: "Em andamento" })[
    value
  ] || value;

/** Explain generated/received labels at presentation time; original data stays intact. */
export function explainText(value: string): string {
  return value
    .replace(/Reproducer · confirmar teste RED/g, "Reprodução · confirmar o problema")
    .replace(/Fixer · propor patch mínimo/g, "Correção · preparar a solução")
    .replace(/Verifier · comparar RED \/ GREEN/g, "Verificação · conferir o resultado")
    .replace(/Upload de comprovante retorna erro 500/gi, "Não foi possível enviar o comprovante")
    .replace(
      /\bSHA[- ]?256\b/gi,
      "identificador que confirma a integridade do arquivo",
    )
    .replace(/\b[a-f0-9]{40,}\b/gi, "identificador da versão registrada")
    .replace(
      /\bRED\s*(?:antes,?\s*)?(?:\/|,)?\s*GREEN\b/gi,
      "falha antes da correção e passa depois",
    )
    .replace(/\bRED\b/g, "falha antes da correção")
    .replace(/\bGREEN\b/g, "passa depois da correção")
    .replace(/\bTriage\b/g, "Triagem")
    .replace(/\bReproducer\b/g, "Reprodução")
    .replace(/\bFixer\b/g, "Correção")
    .replace(/\bVerifier\b/g, "Verificação")
    .replace(/\bpatch\b/gi, "correção proposta")
    .replace(/\bsuíte\b/gi, "conjunto de verificações")
    .replace(/\bsandbox\b/gi, "ambiente de verificação")
    .replace(/\bneeds_info\b/g, "aguardando mais informações")
    .replace(/\bCSV\b/g, "planilha")
    .replace(/\berro 500\b/gi, "falha no serviço")
    .replace(/\bdocs\/[\w/.-]+/g, "a documentação do projeto")
    .replace(/\bdemonstração\b/gi, "exemplo")
    .replace(/\bbackend\b/gi, "serviço de acompanhamento")
    .replace(/\bSnapshot\b/gi, "resumo atualizado");
}

export function friendlyError(error: unknown): string {
  if (error instanceof Error && /401|403/.test(error.message))
    return "Você não tem acesso a estas informações. Peça ajuda à equipe responsável.";
  if (error instanceof Error && /404/.test(error.message))
    return "Não encontramos estas informações. Confira o caso e tente novamente.";
  return "Não foi possível confirmar esta atualização. Tente novamente em instantes ou fale com a equipe responsável.";
}
export function caseReason(reason: unknown): string {
  if (typeof reason === "string") return explainText(reason);
  if (reason && typeof reason === "object") {
    const data = reason as Record<string, unknown>;
    for (const key of ["message", "question", "detail", "description"])
      if (typeof data[key] === "string") return explainText(data[key]);
  }
  return "Este caso precisa de uma revisão da equipe antes de continuar.";
}
